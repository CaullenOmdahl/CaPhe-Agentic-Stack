#!/usr/bin/env python3
"""Explicit preparation recipes and private freshness receipts, never completion evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

try:
    from stack_state import StateError, _json_object, _mkdir, _outside_git, _no_symlinks, _owned
except ModuleNotFoundError:
    from tools.stack_state import StateError, _json_object, _mkdir, _outside_git, _no_symlinks, _owned


class PrepareError(ValueError):
    pass


_REQUIRED = {"argv", "cwd", "inputs", "outputs", "toolchain", "env"}
PROCESS_PLATFORM_ERROR = 'Preparation process execution requires macOS or Linux/POSIX; use Linux under WSL on Windows.'


def _require_posix():
    if os.name != 'posix':
        raise PrepareError(PROCESS_PLATFORM_ERROR)


def _argv(value):
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item and '\0' not in item for item in value)


def _relative(value, allow_dot=False):
    return (isinstance(value, str) and bool(value) and '\0' not in value and
            not Path(value).is_absolute() and '..' not in Path(value).parts and
            (allow_dot or value != '.'))


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, dict) or set(manifest) - (_REQUIRED | {'timeout_seconds'}) or _REQUIRED - set(manifest):
        raise PrepareError('recipe has missing or unknown fields')
    if not _argv(manifest['argv']) or not _relative(manifest['cwd'], True):
        raise PrepareError('recipe requires argv and a relative cwd')
    for key in ('inputs', 'outputs'):
        value = manifest[key]
        if not isinstance(value, list) or not value or not all(_relative(item) for item in value) or len(set(value)) != len(value):
            raise PrepareError('declare nonempty unique relative input and output file lists')
    if set(manifest['inputs']) & set(manifest['outputs']):
        raise PrepareError('generated outputs cannot replace declared inputs')
    if not isinstance(manifest['toolchain'], list) or not manifest['toolchain'] or not all(_argv(item) for item in manifest['toolchain']):
        raise PrepareError('declare toolchain probe argv lists')
    if not isinstance(manifest['env'], dict):
        raise PrepareError('env must be explicit non-secret string values')
    for key, value in manifest['env'].items():
        if (not isinstance(key, str) or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) is None or
                key.startswith('GIT_') or key in ('HOME', 'CODEX_HOME') or
                not isinstance(value, str) or '\0' in value or '$' in value):
            raise PrepareError('environment expansion, Git overrides and home overrides are forbidden')
    timeout = manifest.get('timeout_seconds', 900)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > 7200:
        raise PrepareError('timeout_seconds must be positive and at most 7200')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _path(root, relative):
    path = root / relative
    try:
        _no_symlinks(path)
    except StateError as error:
        raise PrepareError(str(error)) from error
    if root not in (path.resolve(), *path.resolve().parents):
        raise PrepareError('recipe path escapes root')
    return path


def _files(root, names):
    result = {}
    for name in names:
        path = _path(root, name)
        if not path.exists():
            result[name] = None
            continue
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise PrepareError('recipe paths must be regular files')
            digest = hashlib.sha256()
            for block in iter(lambda: handle.read(1048576), b''):
                digest.update(block)
            after = os.fstat(handle.fileno())
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise PrepareError('recipe file changed during hashing')
        result[name] = {'sha256': digest.hexdigest(), 'mode': before.st_mode & 0o777}
    return result


def _probe_files(root, names):
    """Return a transient content-plus-stat snapshot for probe mutation checks."""
    result = {}
    for name in names:
        path = _path(root, name)
        if not path.exists():
            result[name] = None
            continue
        before = path.stat()
        file = _files(root, [name])[name]
        after = path.stat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                 info.st_mtime_ns, info.st_ctime_ns)
        if file is None or identity(before) != identity(after):
            raise PrepareError('recipe file changed during probe snapshot')
        result[name] = {'file': file, 'stat': identity(after)}
    return result


def _environment(manifest):
    # Tool discovery, home and temp are the only implicit variables. Values stay hashed in receipts.
    environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT') if key in os.environ}
    environment.update(manifest['env'])
    return environment


def _run(argv, cwd, environment, timeout):
    _require_posix()
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, bufsize=0, start_new_session=True)
    except OSError:
        return {'exit_code': 127, 'output_digest': None}
    digest = hashlib.sha256()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                for key, _ in selector.select(remaining):
                    try:
                        block = os.read(key.fd, 65_536)
                    except BlockingIOError:
                        continue
                    if block:
                        digest.update(block)
                    else:
                        selector.unregister(key.fileobj)
        # EOF can arrive before the child exits; both belong to the same deadline.
        code = process.wait(timeout=max(0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        code = 124
    finally:
        # Escaped descendants must lose their reader, not inherit an ever-growing spool.
        process.stdout.close()
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
    return {'exit_code': code, 'output_digest': digest.hexdigest()}


def _identity(root, manifest):
    _require_posix()
    validate_manifest(manifest)
    cwd = _path(root, manifest['cwd'])
    if not cwd.is_dir():
        raise PrepareError('recipe cwd does not exist')
    environment = _environment(manifest)
    inputs = _files(root, manifest['inputs'])
    input_snapshot = _probe_files(root, manifest['inputs'])
    output_snapshot = _probe_files(root, manifest['outputs'])
    toolchain = []
    for command in manifest['toolchain']:
        toolchain.append(_run(command, cwd, environment, 10))
        if input_snapshot != _probe_files(root, manifest['inputs']):
            raise PrepareError('toolchain probe changed recipe inputs')
        if output_snapshot != _probe_files(root, manifest['outputs']):
            raise PrepareError('toolchain probe changed recipe outputs')
    return {'root_digest': _hash(str(root)), 'recipe_digest': _hash(manifest),
            'inputs': inputs, 'environment_digest': _hash(environment), 'toolchain': toolchain}


def _valid_identity(identity):
    return all(value is not None for value in identity['inputs'].values()) and all(item['exit_code'] == 0 for item in identity['toolchain'])


def _receipt_directory(root, requested, *, create=True):
    path = Path(requested).expanduser().absolute()
    try:
        _no_symlinks(path)
        path = Path(os.path.normpath(path))
        _no_symlinks(path)
    except StateError as error:
        raise PrepareError(str(error)) from error
    path = path.resolve()
    if path == root or root in path.parents:
        raise PrepareError('preparation receipts must be outside the source root')
    parts = tuple(part.casefold() for part in path.parts)
    if any(left == '.codex' and right in ('memories', 'sessions') for left, right in zip(parts, parts[1:])):
        raise PrepareError('canonical records cannot store preparation receipts')
    try:
        _no_symlinks(path)
        _outside_git(path)
        if create:
            _mkdir(path)
        else:
            _owned(path, directory=True)
    except StateError as error:
        raise PrepareError(str(error)) from error
    return path


def read_receipt(root, receipt_path, *, receipt_root):
    """Load only an owner-only receipt from its exact declared private directory.

    This validates local storage provenance, not a trusted-executor attestation.
    The data-only is_fresh helper assumes its caller has already established trust.
    """
    root = Path(root).resolve(strict=True)
    directory = _receipt_directory(root, receipt_root, create=False)
    directory_before = directory.stat()
    path = Path(receipt_path).expanduser().absolute()
    try:
        _no_symlinks(path)
        path = path.resolve(strict=True)
        if path.parent != directory:
            raise PrepareError('receipt is outside its declared private directory')
        _owned(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_mode & 0o077:
                raise PrepareError('receipt must be an owner-only regular file')
            content = handle.read(1_048_577)
            after = os.fstat(handle.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                 info.st_ctime_ns, info.st_mode, info.st_uid)
        _owned(path)
        if len(content) > 1_048_576 or identity(before) != identity(after) or identity(after) != identity(path.stat()):
            raise PrepareError('receipt changed or exceeds the size limit')
        _receipt_directory(root, directory, create=False)
        current = directory.stat()
        if (directory_before.st_dev, directory_before.st_ino) != (current.st_dev, current.st_ino):
            raise PrepareError('receipt directory changed while reading')
        return json.loads(content, object_pairs_hook=_json_object)
    except (StateError, RecursionError) as error:
        raise PrepareError('invalid private receipt') from error


def run_prepare(root: Path | str, manifest: Mapping[str, Any], *, receipt_root: Path | str) -> dict:
    _require_posix()
    root = Path(root).resolve(strict=True)
    directory = _receipt_directory(root, receipt_root)
    original_directory = directory.stat()
    before = _identity(root, manifest)
    _files(root, manifest['outputs'])  # Preflight output symlinks before executing the recipe.
    started = time.monotonic()
    outcome = {'exit_code': None, 'output_digest': None}
    if _valid_identity(before):
        outcome = _run(manifest['argv'], _path(root, manifest['cwd']), _environment(manifest), manifest.get('timeout_seconds', 900))
    after = _identity(root, manifest)
    outputs = _files(root, manifest['outputs'])
    success = (_valid_identity(before) and before == after and outcome['exit_code'] == 0 and
               all(value is not None for value in outputs.values()))
    receipt = {'version': 1, 'identity': before, 'outputs': outputs, 'success': success,
               'outcome': outcome, 'source_changed': before != after,
               'elapsed_ms': round((time.monotonic() - started) * 1000)}
    _receipt_directory(root, directory)
    current_directory = directory.stat()
    if (original_directory.st_dev, original_directory.st_ino) != (current_directory.st_dev, current_directory.st_ino):
        raise PrepareError('receipt directory changed during preparation')
    descriptor, name = tempfile.mkstemp(prefix='prepare-', suffix='.json', dir=directory)
    receipt['receipt_path'] = name
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(receipt, handle, sort_keys=True, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    return receipt


def is_fresh(root: Path | str, manifest: Mapping[str, Any], receipt: Mapping[str, Any]) -> bool:
    try:
        root = Path(root).resolve(strict=True)
        identity = _identity(root, manifest)
        return (isinstance(receipt, dict) and receipt.get('version') == 1 and receipt.get('success') is True and
                receipt.get('source_changed') is False and isinstance(receipt.get('outcome'), dict) and
                receipt['outcome'].get('exit_code') == 0 and
                _valid_identity(identity) and receipt.get('identity') == identity and
                set(receipt.get('outputs', {})) == set(manifest['outputs']) and
                all(value is not None for value in receipt['outputs'].values()) and
                receipt['outputs'] == _files(root, manifest['outputs']))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--receipt-root', required=True)
    parser.add_argument('--check-receipt', help='Check freshness without running the preparation command')
    args = parser.parse_args(argv)
    if os.name != 'posix':
        parser.exit(2, PROCESS_PLATFORM_ERROR + '\n')
    try:
        manifest = json.loads(Path(args.manifest).read_text(), object_pairs_hook=_json_object)
        if args.check_receipt:
            receipt = read_receipt(args.root, args.check_receipt, receipt_root=args.receipt_root)
            fresh = is_fresh(args.root, manifest, receipt)
            if fresh:
                # Toolchain probes also run during identity collection; retain
                # the private-storage boundary after those commands finish.
                fresh = read_receipt(args.root, args.check_receipt, receipt_root=args.receipt_root) == receipt
            print(json.dumps({'fresh': fresh}))
            return 0 if fresh else 1
        receipt = run_prepare(args.root, manifest, receipt_root=args.receipt_root)
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['success'] else 1
    except (OSError, ValueError) as error:
        parser.exit(2, f'preparation rejected: {type(error).__name__}\n')


if __name__ == '__main__':
    raise SystemExit(main())
