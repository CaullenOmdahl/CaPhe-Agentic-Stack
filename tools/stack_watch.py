#!/usr/bin/env python3
"""Bounded, read-only status queries and opt-in masking of identical successful payloads."""

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

MAX_QUERY_BYTES = 65_536
MAX_EVENT_BYTES = 4096
_STATUSES = frozenset(('UNKNOWN', 'QUEUED', 'PENDING', 'RUNNING', 'IN_PROGRESS', 'WAITING',
                       'INPUT_NEEDED', 'COMPLETED', 'SUCCESS', 'TERMINAL', 'DONE',
                       'FAILURE', 'FAILED', 'ERROR', 'QUERY_FAILURE'))
_CONCLUSIONS = frozenset(('SUCCESS', 'FAILURE', 'FAILED', 'ERROR', 'CANCELLED', 'TIMED_OUT',
                          'SKIPPED', 'NEUTRAL', 'ACTION_REQUIRED', 'STALE'))
_FAILURES = frozenset(('FAILURE', 'FAILED', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'STALE'))
_REASONS = frozenset(('invalid_json', 'malformed_observation', 'timed_out', 'unavailable',
                      'output_limit', 'process_exit'))
_LOCATOR = re.compile(r'[A-Za-z0-9_.:/@#-]{1,160}\Z')
_DIGEST = re.compile(r'(?:[a-f0-9]{40}|[a-f0-9]{64})\Z')
_CREDENTIAL = re.compile(r'\b(?:' + 'sk' + r'-|gh[pousr]_|github' + r'_pat_)[A-Za-z0-9_-]{12,}')


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _duration(value: float, *, positive: bool = False) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError('duration must be finite and non-negative; intervals must be positive')


def project_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Closed output contract; unknown raw fields never affect comparison or output."""
    if not isinstance(raw, Mapping) or not isinstance(raw.get('status'), str) or raw['status'].upper() not in _STATUSES:
        raise ValueError('invalid status')
    result = {'status': raw['status'].upper()}
    if 'conclusion' in raw:
        conclusion = raw['conclusion']
        if conclusion is not None and (not isinstance(conclusion, str) or conclusion.upper() not in _CONCLUSIONS):
            raise ValueError('invalid conclusion')
        result['conclusion'] = conclusion.upper() if conclusion else None
    if 'input_needed' in raw:
        if type(raw['input_needed']) is not bool:
            raise ValueError('invalid input-needed flag')
        result['input_needed'] = raw['input_needed']
    if 'decision' in raw:
        if raw['decision'] not in ('required', 'approved', 'rejected', 'none'):
            raise ValueError('invalid decision')
        result['decision'] = raw['decision']
    for field in ('source', 'scope'):
        if field in raw:
            value = raw[field]
            if not isinstance(value, str) or not _LOCATOR.fullmatch(value) or _CREDENTIAL.search(value):
                raise ValueError('invalid source or scope')
            result[field] = value
    if 'digest' in raw:
        if not isinstance(raw['digest'], str) or not _DIGEST.fullmatch(raw['digest']):
            raise ValueError('invalid source digest')
        result['digest'] = raw['digest']
    if 'exit_code' in raw:
        # Preserve POSIX signals and signed/unsigned native Windows status codes.
        if (result['status'] != 'QUERY_FAILURE' or type(raw['exit_code']) is not int
                or not -(2 ** 31) <= raw['exit_code'] <= 2 ** 32 - 1):
            raise ValueError('invalid query exit code')
        result['exit_code'] = raw['exit_code']
    if 'failure_reason' in raw:
        if result['status'] != 'QUERY_FAILURE' or not isinstance(raw['failure_reason'], str) or raw['failure_reason'] not in _REASONS:
            raise ValueError('invalid query failure reason')
        result['failure_reason'] = raw['failure_reason']
    return result


def observation_fingerprint(observation: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json(project_observation(observation))).hexdigest()


def classify_observation(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    projected = project_observation(current)
    fingerprint = hashlib.sha256(_json(projected)).hexdigest()
    changed = previous is None or fingerprint != observation_fingerprint(previous)
    status, conclusion = projected['status'], projected.get('conclusion')
    if status == 'QUERY_FAILURE' or status in _FAILURES or conclusion in _FAILURES:
        state, actionable = 'failure', True
    elif (projected.get('input_needed') or status in ('WAITING', 'INPUT_NEEDED')
          or projected.get('decision') == 'required' or conclusion == 'ACTION_REQUIRED'):
        state, actionable = 'input-needed', True
    elif status in ('COMPLETED', 'SUCCESS', 'TERMINAL', 'DONE'):
        state, actionable = 'terminal', True
    else:
        state, actionable = ('changed', True) if changed else ('unchanged', False)
    return {'state': state, 'actionable': actionable, 'fingerprint': fingerprint, 'observation': projected}


def _query_failure(reason: str, exit_code: int | None = None) -> dict[str, Any]:
    result = {'status': 'QUERY_FAILURE', 'conclusion': 'TIMED_OUT' if reason == 'timed_out' else 'FAILURE',
              'source': 'process-query', 'failure_reason': reason}
    if exit_code is not None:
        result['exit_code'] = exit_code
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse_status_query(stdout: str | bytes) -> dict[str, Any]:
    if not isinstance(stdout, (str, bytes)) or len(stdout) > MAX_QUERY_BYTES:
        return _query_failure('output_limit')
    try:
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8')
        if len(stdout.encode('utf-8')) > MAX_QUERY_BYTES:
            return _query_failure('output_limit')
        def invalid_constant(_):
            raise ValueError('nonfinite JSON number')
        value = json.loads(stdout, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        return _query_failure('invalid_json')
    try:
        return project_observation(value)
    except ValueError:
        return _query_failure('malformed_observation')


def _stop(process) -> None:
    # Kill the query's process group as well: a child may otherwise retain the output pipe.
    try:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def run_process_observation(argv: Sequence[str], timeout_seconds: float = 15) -> dict[str, Any]:
    """Execute an explicitly supplied read-only JSON query, with a byte cap and deadline."""
    _duration(timeout_seconds, positive=True)
    if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or not arg or '\0' in arg for arg in argv):
        raise ValueError('explicit query argv is required')
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(list(argv), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=(os.name == 'posix'))
    except OSError:
        return _query_failure('unavailable', 127)
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout_seconds)
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, min(8192, MAX_QUERY_BYTES + 1 - len(output)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_QUERY_BYTES:
                            _stop(process)
                            return _query_failure('output_limit')
            remaining = deadline - time.monotonic()
            if remaining <= 0 and process.poll() is None:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            code = process.wait(timeout=max(0, remaining))
        if code != 0:
            return _query_failure('process_exit', code)
        return parse_status_query(bytes(output))
    except subprocess.TimeoutExpired:
        _stop(process)
        return _query_failure('timed_out', 124)
    except OSError:
        _stop(process)
        return _query_failure('unavailable')
    finally:
        process.stdout.close()


def watch(argv: Sequence[str], *, timeout_seconds: float, poll_interval_seconds: float,
          process_timeout_seconds: float = 15) -> dict[str, Any]:
    """Poll explicit query argv; every subprocess timeout is capped by the total remaining budget.

    Arbitrary fetch callbacks are intentionally unsupported: they cannot be cancelled safely.
    A zero duration performs no query and returns an explicit timeout.
    """
    _duration(timeout_seconds)
    _duration(poll_interval_seconds, positive=True)
    _duration(process_timeout_seconds, positive=True)
    if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence) or not argv:
        raise ValueError('explicit query argv is required')
    deadline, previous, event = time.monotonic() + timeout_seconds, None, None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result = {'state': 'timeout', 'actionable': False}
            if event is not None:
                result['last'] = event
            return result
        current = run_process_observation(argv, min(process_timeout_seconds, remaining))
        event = classify_observation(current, current if previous is None else previous)
        if event['actionable']:
            return event
        previous = event['observation']
        time.sleep(min(poll_interval_seconds, max(0, deadline - time.monotonic())))


def _mask_hash(raw: Mapping[str, Any]) -> str:
    # A supplied hash is metadata, never evidence. Hash actual canonical content ourselves.
    digest, size = hashlib.sha256(), 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    for part in encoder.iterencode({key: value for key, value in raw.items() if key != 'payload_sha256'}):
        block = part.encode()
        size += len(block)
        if size > 32 * 1024 * 1024:
            raise ValueError('mask payload exceeds bound')
        digest.update(block)
    return digest.hexdigest()


def _maskable(raw: Mapping[str, Any]) -> bool:
    allowed = {'status', 'conclusion', 'source', 'digest', 'scope', 'payload', 'payload_sha256', 'input_needed'}
    if set(raw) - allowed or 'payload' not in raw:
        return False
    projected = project_observation(raw)
    return (projected['status'] == 'COMPLETED' and projected.get('conclusion') == 'SUCCESS'
            and not projected.get('input_needed') and all(field in projected for field in ('source', 'digest', 'scope')))


def apply_conditional_mask(current: Mapping[str, Any], previous: Mapping[str, Any] | None,
                           *, enabled: bool = False) -> dict[str, Any]:
    """Default off. Replace only an identical, complete successful observation's raw payload.

    The caller retains the canonical original. Decisions, evidence, failures and changed states
    are never eligible. This is a display transform, not authorization or a new success claim.
    """
    result = dict(current)
    if enabled is not True or not isinstance(previous, Mapping):
        return result
    try:
        if not _maskable(current) or not _maskable(previous) or _mask_hash(current) != _mask_hash(previous):
            return result
        return {**project_observation(current), 'masked_from': 'prior-success', 'payload_sha256': _mask_hash(current)}
    except (ValueError, TypeError, RecursionError):
        return result


def restore_mask(masked: Mapping[str, Any], raw: Any) -> Any:
    if (not isinstance(raw, Mapping) or masked.get('masked_from') != 'prior-success'
            or not _maskable(raw) or _mask_hash(raw) != masked.get('payload_sha256')
            or project_observation(masked) != project_observation(raw)):
        raise ValueError('raw payload does not match masked identity')
    return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Read-only bounded JSON status watcher; never sends messages.')
    parser.add_argument('--timeout', type=float, default=0, help='total seconds; zero performs no query')
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--process-timeout', type=float, default=15)
    parser.add_argument('--process', nargs=argparse.REMAINDER, help='explicit read-only JSON status-query argv')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.process:
        parser.error('--process is required')
    try:
        event = watch(args.process, timeout_seconds=args.timeout, poll_interval_seconds=args.interval,
                      process_timeout_seconds=args.process_timeout)
        encoded = _json(event) + b'\n'
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValueError('event exceeds bound')
        sys.stdout.buffer.write(encoded)
        return 1 if event['state'] == 'failure' else 0
    except ValueError:
        sys.stderr.buffer.write(b'{"error":"InvalidWatchConfiguration"}\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
