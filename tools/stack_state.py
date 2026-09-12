#!/usr/bin/env python3
"""Owner-only task continuation and scoped authorization, outside Git worktrees.

This private store has no public exporter and does not edit canonical memories.
Authorization records preserve statements; they are not an authorization oracle.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


class StateError(ValueError):
    pass


def _json_object(pairs):
    """Reject ambiguous object members at every nesting level before validation."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise StateError('JSON object contains duplicate keys')
        result[key] = value
    return result


def _identifier(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value) is None:
        raise StateError('invalid state identifier')
    return value


def _repository(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}', value) is None:
        raise StateError('repository must be a logical owner/name scope')
    return value


def _no_symlinks(path):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise StateError('private state cannot use symlink paths')


def _git_environment():
    return {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}


def _outside_git(path):
    if '.git' in path.parts:
        raise StateError('Git metadata cannot store private state')
    ancestors = (path, *path.parents)
    for ancestor in ancestors:
        if (ancestor / '.git').exists() or (ancestor / '.git').is_symlink():
            raise StateError('private state must be outside all Git worktrees and Git metadata')
    nearest = next(ancestor for ancestor in ancestors if ancestor.exists())
    try:
        result = subprocess.run(['git', '-C', str(nearest), 'rev-parse', '--git-dir'],
                                capture_output=True, text=True,
                                env={**_git_environment(), 'LC_ALL': 'C'}, check=False)
    except OSError as error:
        raise StateError('private state Git boundary could not be verified') from error
    if result.returncode == 0:
        raise StateError('private state must be outside all Git worktrees and Git metadata')
    ordinary_nonrepo = result.stderr == 'fatal: not a git repository (or any of the parent directories): .git\n'
    filesystem_boundary = re.fullmatch(
        r'fatal: not a git repository \(or any parent up to mount point [^\n]+\)\n'
        r'Stopping at filesystem boundary \(GIT_DISCOVERY_ACROSS_FILESYSTEM not set\)\.\n', result.stderr)
    if result.returncode != 128 or not (ordinary_nonrepo or filesystem_boundary):
        raise StateError('private state Git boundary could not be verified')


def _owned(path, directory=False):
    _no_symlinks(path)
    information = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(information.st_mode) or information.st_uid != os.getuid() or information.st_mode & 0o077:
        raise StateError('private state must be owner-only and owned by the current user')


def _mkdir(path):
    _no_symlinks(path)
    if not path.exists():
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for item in reversed(missing):
            try:
                item.mkdir(mode=0o700)
            except FileExistsError:
                pass
            _owned(item, directory=True)
    _owned(path, directory=True)


def _encode(record):
    try:
        encoded = json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + '\n'
    except (ValueError, TypeError) as error:
        raise StateError('private state must be JSON data') from error
    if len(encoded.encode('utf-8')) > 1_048_576:
        raise StateError('private state record exceeds 1 MiB')
    return encoded


class PrivateStateStore:
    def __init__(self, base: Path, repo_root: Path, repository: str):
        self.repository = _repository(repository)
        self.repo_root = Path(repo_root).resolve(strict=True)
        self.base = Path(base).absolute()
        _no_symlinks(self.base)
        self.base = Path(os.path.normpath(self.base))
        _no_symlinks(self.base)
        if any(left.casefold() == '.codex' and right.casefold() in ('memories', 'sessions')
               for left, right in zip(self.base.parts, self.base.parts[1:])):
            raise StateError('canonical memory and transcript directories cannot store task state')
        if self.base == self.repo_root or self.repo_root in self.base.parents:
            raise StateError('private state cannot be inside its repository')
        _outside_git(self.base)
        _mkdir(self.base)
        digest = hashlib.sha256(self.repository.encode('utf-8')).hexdigest()
        self.directory = self.base / 'repositories' / digest
        _mkdir(self.directory)
        for namespace in ('tasks', 'authorizations'):
            _mkdir(self.directory / namespace)

    def _check(self):
        _outside_git(self.base)
        _owned(self.base, directory=True)
        for path in (self.directory.parent, self.directory):
            _owned(path, directory=True)

    @contextmanager
    def _locked(self):
        self._check()
        path = self.directory / '.lock'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            _owned(path)
            self._check()
            yield
        finally:
            os.close(descriptor)

    def _path(self, namespace, identifier):
        _identifier(identifier)
        directory = self.directory / namespace
        _owned(directory, directory=True)
        path = directory / (identifier + '.json')
        _no_symlinks(path)
        return path

    def _read(self, namespace, identifier):
        path = self._path(namespace, identifier)
        if not path.exists():
            return None
        _owned(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            with os.fdopen(descriptor, 'r', encoding='utf-8') as handle:
                content = handle.read(1_048_577)
            if len(content.encode('utf-8')) > 1_048_576:
                raise StateError('private state record exceeds 1 MiB')
            record = json.loads(content, object_pairs_hook=_json_object)
        except (ValueError, OSError) as error:
            raise StateError('invalid private state record') from error
        if not isinstance(record, dict) or set(record) != {'schema_version', 'repository', 'id', 'data'}:
            raise StateError('invalid private state envelope')
        if record['schema_version'] != 1 or record['repository'] != self.repository or record['id'] != identifier:
            raise StateError('private state scope mismatch')
        if not isinstance(record['data'], dict):
            raise StateError('private state data must be an object')
        return record['data']

    def _write(self, namespace, identifier, data, immutable=False):
        if not isinstance(data, dict):
            raise StateError('private state data must be an object')
        content = _encode({'schema_version': 1, 'repository': self.repository,
                           'id': _identifier(identifier), 'data': data})
        with self._locked():
            path = self._path(namespace, identifier)
            previous = self._read(namespace, identifier)
            if previous is not None and immutable:
                if _encode(previous) == _encode(data):
                    return path
                raise StateError('authorization id is immutable; use a new explicit record')
            descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._check()
                self._path(namespace, identifier)
                if immutable:
                    try:
                        os.link(temporary, path)
                    except FileExistsError as error:
                        raise StateError('authorization id already exists') from error
                else:
                    os.replace(temporary, path)
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                temporary.unlink(missing_ok=True)
            return path

    def write_task(self, identifier, data):
        return self._write('tasks', identifier, data)

    def read_task(self, identifier):
        with self._locked():
            return self._read('tasks', identifier)

    def write_authorization(self, identifier, data):
        required = {'action', 'scope', 'user_statement'}
        if not isinstance(data, dict) or set(data) != required or any(not isinstance(data[key], str) or not data[key].strip() for key in required):
            raise StateError('authorization requires action, scope, and original user statement')
        if data['scope'] != self.repository:
            raise StateError('authorization scope does not match repository')
        return self._write('authorizations', identifier, data, immutable=True)

    def read_authorization(self, identifier):
        with self._locked():
            return self._read('authorizations', identifier)
