#!/usr/bin/env python3
"""Private, read-only context projections; incomplete collection never attests freshness."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

DEFAULT_MAX_BYTES = 16_384
_BLOCK = 256 * 1024
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.:/@#-]{1,160}\Z')
_DIGEST = re.compile(r'[a-f0-9]{64}\Z')
_SECRET = re.compile(r'(?i)\b(api[_ -]?key|token|password|secret|authorization)\s*[:=]\s*[^\s,;]+|\bBearer\s+[^\s,;]+')
_CREDENTIAL = re.compile(r'\b(?:' + 'sk' + r'-|gh[pousr]_|github' + r'_pat_)[A-Za-z0-9_-]{12,}')


def isolated_git_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    # Strip numbered config overrides and future repository-local Git variables too.
    env = {k: v for k, v in (os.environ if base is None else base).items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    return env


def _sanitize_excerpt(value: str) -> str:
    return _CREDENTIAL.sub('[redacted]', _SECRET.sub('[redacted]', value))


def _text(value: str | bytes | None) -> str:
    return value.decode('utf-8', 'replace') if isinstance(value, bytes) else (value or '')


def _excerpt(value: str | bytes | None, limit: int = 512) -> str:
    clean = _sanitize_excerpt(_text(value))
    return clean if len(clean) <= limit else clean[:limit] + '…[truncated]'


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def _cli_encoded(value: Any) -> bytes:
    return _encoded(value) + b'\n'


def _bound(value: int, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError('invalid projection bound')


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None and _sanitize_excerpt(value) == value


def command_projection(argv: Sequence[str], *, returncode: int, stdout: str | bytes,
                       stderr: str | bytes, source: str = 'subprocess') -> dict[str, Any]:
    return {'source': {'kind': _excerpt(source, 64), 'argv': [_excerpt(arg, 80) for arg in argv[:16]]},
            'exit_code': returncode, 'failed': returncode != 0,
            'stdout_excerpt': _excerpt(stdout), 'stderr_excerpt': _excerpt(stderr)}


def _run(argv: Sequence[str], cwd: Path, timeout_seconds: float = 10) -> dict[str, Any]:
    # Anonymous owner-only temporary files keep arbitrarily large command output off the heap.
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(list(argv), cwd=cwd, env=isolated_git_environment(),
                                    stdout=stdout, stderr=stderr, timeout=timeout_seconds, check=False)
            stdout.seek(0)
            stderr.seek(0)
            return command_projection(argv, returncode=result.returncode,
                                      stdout=stdout.read(2048), stderr=stderr.read(2048))
    except subprocess.TimeoutExpired:
        return command_projection(argv, returncode=124, stdout='', stderr='command timed out')
    except OSError:
        return command_projection(argv, returncode=127, stdout='', stderr='command unavailable')


class SnapshotFailure(ValueError):
    def __init__(self, operation: str, exit_code: int | None = None):
        super().__init__('snapshot incomplete')
        self.operation, self.exit_code = operation, exit_code


@contextmanager
def _git_output(repo: Path, operation: str, args: Sequence[str], accepted=(0,)):
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.run(['git', '-c', 'core.fsmonitor=false', *args], cwd=repo,
                                     env=isolated_git_environment(), stdout=output,
                                     stderr=subprocess.DEVNULL, check=False, timeout=10)
        except subprocess.TimeoutExpired:
            raise SnapshotFailure(operation, 124) from None
        except OSError:
            raise SnapshotFailure(operation, 127) from None
        if process.returncode not in accepted:
            raise SnapshotFailure(operation, process.returncode)
        output.seek(0)
        yield output, process.returncode


def _records(handle):
    pending = b''
    for chunk in iter(lambda: handle.read(_BLOCK), b''):
        records = (pending + chunk).split(b'\0')
        pending = records.pop()
        if len(pending) > 1024 * 1024:
            raise SnapshotFailure('oversized-path')
        yield from records
    if pending:
        raise SnapshotFailure('unterminated-path')


def _hash_stream(digest, label: bytes, handle) -> None:
    digest.update(label + b'\0' + os.fstat(handle.fileno()).st_size.to_bytes(8, 'big'))
    for chunk in iter(lambda: handle.read(_BLOCK), b''):
        digest.update(chunk)


def _hash_worktree_path(digest, root_fd: int, relative: bytes, *, allow_missing=False) -> None:
    parts = relative.split(b'/')
    if not parts or any(part in (b'', b'.', b'..') for part in parts):
        raise SnapshotFailure('unsafe-path')
    parent = os.dup(root_fd)
    try:
        digest.update(b'path\0' + len(relative).to_bytes(8, 'big') + relative)
        try:
            for index, part in enumerate(parts[:-1]):
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                except NotADirectoryError:
                    if not allow_missing:
                        raise
                    # A file/symlink can replace the directory containing a tracked path.
                    # Bind that blocker itself, even if an ignore rule hides it from status.
                    _hash_worktree_path(digest, root_fd, b'/'.join(parts[:index + 1]))
                    digest.update(b'blocked-descendant\0')
                    return
                os.close(parent)
                parent = child
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if not allow_missing:
                raise
            digest.update(b'missing\0')
            return
        if stat.S_ISDIR(before.st_mode) and allow_missing:
            # Git lists visible descendants separately. Directory size/mtime can change
            # because of ignored children, so only presence and mode enter the digest.
            digest.update(f'{before.st_mode}:directory\0'.encode())
            after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        elif stat.S_ISLNK(before.st_mode):
            digest.update(f'{before.st_mode}:{before.st_size}\0'.encode())
            digest.update(os.fsencode(os.readlink(parts[-1], dir_fd=parent)))
            after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        else:
            digest.update(f'{before.st_mode}:{before.st_size}\0'.encode())
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as handle:
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode) or opened.st_ino != before.st_ino:
                    raise SnapshotFailure('unsupported-or-changed-path')
                for block in iter(lambda: handle.read(_BLOCK), b''):
                    digest.update(block)
                after = os.fstat(handle.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise SnapshotFailure('path-changed-during-read')
    except OSError:
        raise SnapshotFailure('path-unreadable-or-changed') from None
    finally:
        os.close(parent)


def _snapshot_identity(repo: Path) -> dict[str, Any]:
    head = None
    try:
        with _git_output(repo, 'repository', ['rev-parse', '--is-inside-work-tree']) as (handle, _):
            if handle.read(32).strip() != b'true':
                raise SnapshotFailure('repository')
        with _git_output(repo, 'head', ['rev-parse', '--verify', '--quiet', 'HEAD'], accepted=(0, 1)) as (handle, code):
            if code == 0:
                head = handle.read(128).decode('ascii').strip()
                if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', head):
                    raise SnapshotFailure('head')
        digest = hashlib.sha256(b'caphe-context-snapshot-v3\0' + (head or 'unborn').encode())
        # Index modes, stages and blob IDs bind staging even when worktree bytes are unchanged.
        with _git_output(repo, 'index', ['ls-files', '--stage', '-z']) as (handle, _):
            _hash_stream(digest, b'index', handle)
            handle.seek(0)
            if any(record.startswith(b'160000 ') for record in _records(handle)):
                raise SnapshotFailure('submodule-snapshot-unsupported')
            with _git_output(repo, 'index-flags', ['ls-files', '-v', '-z']) as (flags, _):
                if any(record[:1].islower() or record.startswith(b'S ') for record in _records(flags)):
                    raise SnapshotFailure('hidden-worktree-paths-unsupported')
            handle.seek(0)
            root_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                # Git clean filters can make different executable bytes produce the same diff.
                # Bind raw tracked files, modes and symlink targets without running filters.
                for record in _records(handle):
                    relative = record.split(b'\t', 1)[1]
                    _hash_worktree_path(digest, root_fd, relative, allow_missing=True)
            finally:
                os.close(root_fd)
        with _git_output(repo, 'untracked', ['ls-files', '--others', '--exclude-standard', '-z']) as (handle, _):
            root_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for relative in _records(handle):
                    _hash_worktree_path(digest, root_fd, relative)
            finally:
                os.close(root_fd)
        return {'head': head, 'working_snapshot': digest.hexdigest(), 'complete': True}
    except (SnapshotFailure, OSError, UnicodeError) as exc:
        return {'head': head, 'working_snapshot': None, 'complete': False,
                'failure': {'operation': exc.operation if isinstance(exc, SnapshotFailure) else 'snapshot',
                            'exit_code': exc.exit_code if isinstance(exc, SnapshotFailure) else None}}


def mark_snapshot_freshness(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    complete = all(item.get('complete') is True and isinstance(item.get('working_snapshot'), str)
                   and _DIGEST.fullmatch(item['working_snapshot']) for item in (before, after))
    return {'before': dict(before), 'after': dict(after), 'stale': not complete or before != after}


def _status_records(records, max_paths: int) -> dict[str, Any]:
    paths, omitted = [], 0
    iterator = iter(records)
    for record in iterator:
        if len(record) < 4 or record[2:3] != b' ':
            raise ValueError('malformed porcelain status')
        state = record[:2].decode('ascii')
        if any(char not in ' MADRCU?!T' for char in state):
            raise ValueError('malformed porcelain status')
        item = {'state': state, 'path': _sanitize_excerpt(os.fsdecode(record[3:]))}
        if 'R' in state or 'C' in state:
            original = next(iterator, None)
            if not original:
                raise ValueError('missing rename origin')
            item['original_path'] = _sanitize_excerpt(os.fsdecode(original))
        if len(paths) < max_paths:
            paths.append(item)
        else:
            omitted += 1
    return {'paths': paths, 'truncated': omitted > 0, 'omitted_count': omitted}


def project_git_status(raw_status: str, max_paths: int = 50) -> dict[str, Any]:
    _bound(max_paths, 0)
    if raw_status and not raw_status.endswith('\0'):
        raise ValueError('unterminated porcelain status')
    return _status_records((os.fsencode(item) for item in raw_status.split('\0')[:-1]), max_paths)


def collect_repository_context(repo: Path | str = '.', max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Emit compact private metadata, with two independent complete snapshot observations."""
    _bound(max_bytes, 128)
    root = Path(repo).resolve()
    # Resolve a supplied subdirectory to the actual worktree root before hashing paths.
    try:
        with _git_output(root, 'root', ['rev-parse', '--show-toplevel']) as (handle, _):
            root = Path(os.fsdecode(handle.read(16384)).rstrip('\n'))
    except SnapshotFailure:
        pass
    before = _snapshot_identity(root)
    commands = {}
    working = {'paths': [], 'truncated': False, 'omitted_count': 0}
    try:
        with _git_output(root, 'status', ['status', '--porcelain=v1', '-z', '--untracked-files=all']) as (handle, _):
            working = _status_records(_records(handle), 50)
        commands['status'] = {'exit_code': 0, 'failed': False}
    except (SnapshotFailure, ValueError) as exc:
        commands['status'] = {'exit_code': getattr(exc, 'exit_code', None), 'failed': True}
    diff = {}
    for label, args in (('unstaged', []), ('staged', ['--cached'])):
        command = _run(['git', '-c', 'core.fsmonitor=false', 'diff', *args, '--stat', '--no-ext-diff', '--no-textconv'], root)
        commands[label] = {'exit_code': command['exit_code'], 'failed': command['failed']}
        diff[label] = command['stdout_excerpt'] if not command['failed'] else None
    after = _snapshot_identity(root)
    identity = mark_snapshot_freshness(before, after)
    complete = before['complete'] and after['complete'] and not any(item['failed'] for item in commands.values())
    identity['stale'] = identity['stale'] or not complete
    result = {'source': {'repository': _sanitize_excerpt(str(root)), 'kind': 'git', 'visibility': 'private'},
              'complete': complete, 'identity': identity, 'working': working, 'diff': diff, 'commands': commands}
    # Shed optional information, preserving exact identities and all command failures.
    if len(_cli_encoded(result)) > max_bytes:
        result['truncated'] = True
        result['diff'] = {'unstaged': None, 'staged': None}
    while len(_cli_encoded(result)) > max_bytes and working['paths']:
        working['paths'].pop()
        working['omitted_count'] += 1
        working['truncated'] = True
    if len(_cli_encoded(result)) > max_bytes:
        raise ValueError('bound cannot contain required context')
    return result


def project_history_envelope(items: Sequence[Any], max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Accept only explicitly supplied message excerpts with closed, sanitized provenance."""
    _bound(max_bytes, 128)
    omissions = dict(reasoning=0, raw_tool_payload=0, malformed=0, byte_limit=0)
    result = {'items': [], 'omissions': omissions, 'truncated': False,
              'source': {'kind': 'history-projection', 'raw_payloads': 'excluded', 'visibility': 'private'}}
    for item in items:
        if isinstance(item, Mapping) and item.get('kind') in ('reasoning', 'tool'):
            omissions['reasoning' if item['kind'] == 'reasoning' else 'raw_tool_payload'] += 1
            continue
        valid = (isinstance(item, Mapping) and set(item) == {'id', 'kind', 'role', 'excerpt', 'source'}
                 and item['kind'] == 'message' and item['role'] in ('user', 'assistant')
                 and _identifier(item['id']) and isinstance(item['excerpt'], str))
        source = item.get('source') if isinstance(item, Mapping) else None
        valid = (valid and isinstance(source, Mapping) and set(source) == {'id', 'coordinate', 'digest'}
                 and _identifier(source['id']) and _identifier(source['coordinate'])
                 and isinstance(source['digest'], str) and _DIGEST.fullmatch(source['digest']))
        if not valid:
            omissions['malformed'] += 1
            continue
        # Excerpts exceeding the entire budget cannot fit; do not duplicate them in memory.
        if len(item['excerpt']) > max_bytes:
            omissions['byte_limit'] += 1
            continue
        candidate = {'id': item['id'], 'role': item['role'], 'excerpt': _sanitize_excerpt(item['excerpt']), 'source': dict(source)}
        result['items'].append(candidate)
        if len(_cli_encoded(result)) > max_bytes:
            result['items'].pop()
            omissions['byte_limit'] += 1
    result['truncated'] = omissions['byte_limit'] > 0
    # Final omission counts may grow by a digit after an earlier item fit.
    while len(_cli_encoded(result)) > max_bytes and result['items']:
        result['items'].pop()
        omissions['byte_limit'] += 1
        result['truncated'] = True
    if len(_cli_encoded(result)) > max_bytes:
        raise ValueError('bound cannot contain history metadata')
    return result


def project_pr_threads(fetch_page: Callable[[str | None], Mapping[str, Any]], max_pages: int = 20,
                       max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Read-only pagination adapter: unresolved outdated threads remain visible."""
    _bound(max_pages, 1)
    _bound(max_bytes, 256)
    cursor, seen = None, set()
    result = {'unresolved': {'current': [], 'outdated': []},
              'pagination': {'complete': False, 'next_cursor': None, 'pages': 0}}
    for _ in range(max_pages):
        try:
            page = fetch_page(cursor)
        except Exception:
            result['failure'] = {'type': 'FetchFailure'}
            break
        if (not isinstance(page, Mapping) or not isinstance(page.get('nodes'), list)
                or not isinstance(page.get('pageInfo'), Mapping)):
            result['failure'] = {'type': 'MalformedResponse'}
            break
        info = page['pageInfo']
        if type(info.get('hasNextPage')) is not bool:
            result['failure'] = {'type': 'MalformedResponse'}
            break
        result['pagination']['pages'] += 1
        for node in page['nodes']:
            if (not isinstance(node, Mapping) or not _identifier(node.get('id'))
                    or type(node.get('isResolved')) is not bool or type(node.get('isOutdated')) is not bool):
                result['failure'] = {'type': 'MalformedResponse'}
                break
            if node['isResolved'] is False:
                target = result['unresolved']['outdated' if node['isOutdated'] else 'current']
                target.append(node['id'])
                if len(_cli_encoded(result)) > max_bytes - 128:
                    target.pop()
                    result['failure'] = {'type': 'ByteLimit'}
                    break
        if 'failure' in result:
            break
        if not info['hasNextPage']:
            result['pagination'].update(complete=True, next_cursor=None)
            break
        following = info.get('endCursor')
        if not _identifier(following) or following in seen:
            result['failure'] = {'type': 'InvalidCursor'}
            break
        seen.add(following)
        cursor = following
        result['pagination']['next_cursor'] = cursor
    else:
        result['failure'] = {'type': 'PaginationLimit'}
    if len(_cli_encoded(result)) > max_bytes:
        raise ValueError('bound cannot contain thread metadata')
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Collect bounded, read-only private repository context.')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES, help='maximum JSON bytes including newline')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = collect_repository_context(args.repo, args.max_bytes)
        sys.stdout.buffer.write(_cli_encoded(result))
        return 0 if result['complete'] else 1
    except (OSError, ValueError):
        sys.stderr.buffer.write(b'{"error":"ContextUnavailable"}\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
