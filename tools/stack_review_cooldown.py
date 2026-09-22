#!/usr/bin/env python3
"""Local review availability ledger. Never contacts providers or grants approval."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps require a timezone')
    return parsed.astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def decide(record, now, subject=None):
    if subject and subject in record.get('reviewed_subjects', []):
        return 'already_reviewed'
    if record.get('retry_after') and now < timestamp(record['retry_after']):
        return 'local_fallback'
    if record.get('lease_until') and now < timestamp(record['lease_until']):
        return 'wait_existing_request'
    return 'one_remote_attempt_allowed'


def transition(record, action, now, subject=None, reason=None, evidence=None,
               reset_at=None, token=None, checked_at=None):
    record = dict(record)
    if action == 'claim':
        decision = decide(record, now, subject)
        if decision != 'one_remote_attempt_allowed':
            return record, decision
        record.update(subject=subject, token=uuid.uuid4().hex,
                      requested_at=iso(now), lease_until=iso(now + timedelta(minutes=10)))
        return record, 'request_reserved'
    lease_active = (record.get('lease_until') is not None
                    and (checked_at or now) < timestamp(record['lease_until']))
    if (token or lease_active) and token != record.get('token'):
        raise ValueError('stale request token')
    if action == 'success':
        if not token or subject != record.get('subject'):
            raise ValueError('success requires the matching request token and subject')
        record.update(last_success_at=iso(now), evidence=evidence, failures=0,
                      retry_after=None, lease_until=None, token=None,
                      reviewed_subjects=list(dict.fromkeys(
                          record.get('reviewed_subjects', []) + [subject]))[-100:])
        return record, 'availability_restored_not_review_approval'
    if action == 'blocked':
        previous = [record.get('blocked_at'), record.get('last_success_at')]
        if any(value and now <= timestamp(value) for value in previous):
            return record, 'older_or_duplicate_observation_ignored'
        failures = record.get('failures', 0) + 1
        if reset_at:
            retry = timestamp(reset_at)
            if retry <= now:
                raise ValueError('provider reset must be later than the observation')
            basis = 'provider_reported_reset'
        else:
            hours = min((24 if reason == 'quota' else 1) * 2 ** min(failures - 1, 8),
                        168 if reason == 'quota' else 24)
            retry = now + timedelta(hours=hours)
            basis = 'estimated_recheck_not_promised_recovery'
        record.update(blocked_at=iso(now), retry_after=iso(retry), basis=basis,
                      reason=reason, evidence=evidence, failures=failures,
                      lease_until=None, token=None)
        return record, 'local_fallback'
    raise ValueError('unknown action')


@contextmanager
def locked_store(root, key):
    root = root.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('state path must not contain symlinks')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('state directory must be owner-only')
    name = hashlib.sha256(key.encode()).hexdigest()
    path = root / (name + '.json')
    fd = os.open(root / (name + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        record = {}
        if path.exists() or path.is_symlink():
            read_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(read_fd) as stream:
                record = json.load(stream)
            if not isinstance(record, dict) or record.get('key') != key or record.get('schema_version') != 1:
                raise ValueError('state scope or version mismatch')
            if type(record.get('failures', 0)) is not int or record.get('failures', 0) < 0:
                raise ValueError('invalid failure counter')
            for field in ('blocked_at', 'last_success_at', 'retry_after', 'lease_until', 'requested_at'):
                if record.get(field) is not None:
                    if not isinstance(record[field], str):
                        raise ValueError('invalid timestamp')
                    timestamp(record[field])
            if not isinstance(record.get('reviewed_subjects', []), list) or not all(
                    isinstance(value, str) for value in record.get('reviewed_subjects', [])):
                raise ValueError('invalid reviewed subjects')
        yield path, record
    finally:
        os.close(fd)


def save(path, record):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'claim', 'blocked', 'success'])
    parser.add_argument('--key', required=True, help='provider:reviewer:account:quota-scope')
    parser.add_argument('--subject', help='owner/repo/pr-number@full-head-commit')
    parser.add_argument('--reason', choices=['quota', 'timeout', 'unavailable'])
    parser.add_argument('--evidence', help='source URL or private diagnostic path, never raw credentials')
    parser.add_argument('--reset-at', help='provider-reported RFC3339 reset time only')
    parser.add_argument('--observed-at', help='timestamp of a blocked provider response; defaults to now')
    parser.add_argument('--token', help='reservation token returned by claim')
    args = parser.parse_args()
    if args.action in ('claim', 'success') and not args.subject:
        parser.error('subject is required')
    if args.action in ('blocked', 'success') and not args.evidence:
        parser.error('evidence is required')
    if args.action == 'blocked' and not args.reason:
        parser.error('reason is required')
    if args.observed_at and args.action != 'blocked':
        parser.error('observed-at is only for a blocked response')
    root = Path.home() / '.local/state/caphe/review-availability'
    try:
        now = datetime.now(timezone.utc)
        observed = timestamp(args.observed_at) if args.observed_at else now
        if observed > now:
            raise ValueError('observation cannot be in the future')
        with locked_store(root, args.key) as (path, record):
            if args.action == 'status':
                decision = decide(record, now, args.subject)
            else:
                record, decision = transition(record, args.action, observed,
                    args.subject, args.reason, args.evidence, args.reset_at, args.token, checked_at=now)
                record.update(schema_version=1, key=args.key)
                save(path, record)
            print(json.dumps({'decision': decision, 'now': iso(now), 'record': record}))
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({'decision': 'stop_state_error', 'error': str(error)}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
