import concurrent.futures
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest

from tools.stack_review_cooldown import decide, locked_store, save, transition


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)

    def test_quota_blocks_other_heads_and_repositories(self):
        record, _ = transition({}, 'blocked', self.now, reason='quota', evidence='url')
        self.assertEqual(decide(record, self.now, 'other/repo/1@new'), 'local_fallback')
        self.assertEqual(record['basis'], 'estimated_recheck_not_promised_recovery')
        self.assertEqual(decide(record, self.now + timedelta(hours=24)), 'one_remote_attempt_allowed')

    def test_provider_reset_is_used(self):
        record, _ = transition({}, 'blocked', self.now, reason='quota', evidence='url',
                               reset_at='2026-09-23T20:00:00+07:00')
        self.assertEqual(record['retry_after'], '2026-09-23T13:00:00Z')
        self.assertEqual(record['basis'], 'provider_reported_reset')

    def test_later_quota_failure_does_not_repeat_completed_review(self):
        record, _ = transition({}, 'claim', self.now, subject='repo/1@abc')
        record, _ = transition(record, 'success', self.now, subject='repo/1@abc',
                               evidence='review-url', token=record['token'])
        record, _ = transition(record, 'blocked', self.now + timedelta(minutes=5),
                               reason='quota', evidence='other-pr-error')
        self.assertEqual(decide(record, self.now + timedelta(minutes=6), 'repo/1@abc'),
                         'already_reviewed')

    def test_invalid_reset_rejected(self):
        for reset in ['2026-09-21T00:00:00Z', '2026-09-23T00:00:00']:
            with self.assertRaises(ValueError):
                transition({}, 'blocked', self.now, reason='quota', reset_at=reset)

    def test_duplicate_observation_does_not_extend_cooldown(self):
        record, _ = transition({}, 'blocked', self.now, reason='quota', evidence='url')
        duplicate, decision = transition(record, 'blocked', self.now, reason='quota', evidence='url')
        self.assertEqual(record, duplicate)
        self.assertEqual(decision, 'older_or_duplicate_observation_ignored')

    def test_failure_backoff_and_success_reset(self):
        record, _ = transition({}, 'blocked', self.now, reason='timeout', evidence='url')
        record, _ = transition(record, 'blocked', self.now + timedelta(hours=2), reason='timeout', evidence='url')
        self.assertEqual(record['retry_after'], '2026-09-22T14:00:00Z')
        record, _ = transition(record, 'claim', self.now + timedelta(hours=5), subject='repo/1@abc')
        record, _ = transition(record, 'success', self.now + timedelta(hours=5),
                               subject='repo/1@abc', evidence='review-url', token=record['token'])
        self.assertEqual(record['failures'], 0)
        self.assertEqual(decide(record, self.now + timedelta(hours=6), 'repo/1@abc'), 'already_reviewed')
        self.assertEqual(decide(record, self.now + timedelta(hours=6), 'repo/1@def'), 'one_remote_attempt_allowed')

    def test_reservation_prevents_duplicate_requests(self):
        record, result = transition({}, 'claim', self.now, subject='repo/1@abc')
        self.assertEqual(result, 'request_reserved')
        other, result = transition(record, 'claim', self.now, subject='repo/2@def')
        self.assertEqual(result, 'wait_existing_request')
        self.assertEqual(other['token'], record['token'])

    def test_stale_worker_cannot_clear_new_reservation(self):
        record, _ = transition({}, 'claim', self.now, subject='repo/1@abc')
        old_token = record['token']
        record, _ = transition(record, 'claim', self.now + timedelta(minutes=11), subject='repo/1@def')
        with self.assertRaises(ValueError):
            transition(record, 'success', self.now, subject='repo/1@abc', token=old_token)

    def test_old_error_cannot_override_newer_success(self):
        record, _ = transition({}, 'claim', self.now, subject='repo/1@abc')
        record, _ = transition(record, 'success', self.now + timedelta(minutes=1),
                               subject='repo/1@abc', evidence='review-url', token=record['token'])
        updated, _ = transition(record, 'blocked', self.now, reason='quota', evidence='old-error')
        self.assertEqual(updated, record)

    def test_structurally_invalid_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in ['[]', '{"key":"account","schema_version":1,"failures":"bad"}']:
                with locked_store(Path(directory), 'account') as (path, _):
                    pass
                path.write_text(content)
                with self.assertRaises(ValueError):
                    with locked_store(Path(directory), 'account'):
                        self.fail('invalid ledger must fail closed')
                path.unlink()

    def test_concurrent_claims_have_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def claim(_):
                with locked_store(root, 'shared-account') as (path, record):
                    record, result = transition(record, 'claim', self.now, subject='repo/1@abc')
                    record.update(schema_version=1, key='shared-account')
                    save(path, record)
                    return result
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(claim, range(16)))
            self.assertEqual(results.count('request_reserved'), 1)

    def test_malformed_state_is_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            with locked_store(Path(directory), 'account') as (path, _):
                path.write_text('{broken')
            with self.assertRaises(ValueError):
                with locked_store(Path(directory), 'account'):
                    self.fail('should not ignore malformed state')

    def test_distribution_installs_helper_and_policy_without_source_dependency(self):
        import subprocess
        import sys
        from tools.stack_install import plan_runtime_install, apply_runtime_plan
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / 'runtime'
            plan = plan_runtime_install(source, target)
            result = apply_runtime_plan(plan, inventory_root=root / 'inventory')
            self.assertTrue(result['verified'])
            self.assertEqual((target / 'docs/review-workflow.md').read_bytes(),
                             (source / 'docs/review-workflow.md').read_bytes())
            helper = target / 'tools/stack_review_cooldown.py'
            result = subprocess.run([sys.executable, str(helper), '--help'],
                                    cwd=root, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--observed-at', result.stdout)
            self.assertFalse((target / 'review-availability').exists())


if __name__ == '__main__':
    unittest.main()
