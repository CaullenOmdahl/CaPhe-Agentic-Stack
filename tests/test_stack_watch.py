import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / 'tools' / 'stack_watch.py'
SPEC = importlib.util.spec_from_file_location('stack_watch', MODULE_PATH)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


def success():
    return {'status': 'COMPLETED', 'conclusion': 'SUCCESS', 'source': 'pr:7',
            'digest': 'a' * 64, 'scope': 'checks', 'payload': {'log': 'x' * 10000}}


class WatchContracts(unittest.TestCase):
    def test_comparison_uses_bounded_projection_before_fingerprinting(self):
        first = {'status': 'RUNNING', 'logs': 'first', 'updatedAt': 'one'}
        second = {'status': 'RUNNING', 'logs': 'x' * 100000, 'updatedAt': 'two'}
        result = watcher.classify_observation(second, first)
        self.assertEqual(result['state'], 'unchanged')
        self.assertLess(len(json.dumps(result)), 4096)
        self.assertNotIn('logs', result['observation'])
        self.assertEqual(watcher.observation_fingerprint(first), watcher.observation_fingerprint(second))

    def test_projected_fields_are_typed_enumerated_bounded_and_sanitized(self):
        for changes in ({'status': 'x' * 10000}, {'source': {'secret': 'canary'}},
                        {'source': 'token=source-canary'}, {'input_needed': 'false'},
                        {'decision': {'token': 'canary'}}, {'digest': 'arbitrary'},
                        {'scope': 'x' * 10000}, {'conclusion': ['SUCCESS']}):
            result = watcher.parse_status_query(json.dumps({'status': 'RUNNING', **changes}))
            self.assertEqual(result['status'], 'QUERY_FAILURE')
            self.assertNotIn('canary', json.dumps(result))
        with self.assertRaises(ValueError):
            watcher.classify_observation({'status': 'RUNNING', 'source': []})

    def test_failure_input_and_terminal_are_always_surfaced(self):
        for raw, state in (({'status': 'COMPLETED', 'conclusion': 'FAILURE'}, 'failure'),
                           ({'status': 'WAITING', 'input_needed': True}, 'input-needed'),
                           ({'status': 'COMPLETED', 'conclusion': 'SUCCESS'}, 'terminal')):
            self.assertEqual(watcher.classify_observation(raw, raw)['state'], state)

    def test_query_timeout_and_exit_are_preserved_separately_from_task_status(self):
        observation = watcher.run_process_observation([sys.executable, '-c', 'import sys; sys.exit(7)'], 1)
        result = watcher.classify_observation(observation)
        self.assertEqual(result['state'], 'failure')
        self.assertEqual(result['observation']['exit_code'], 7)
        timed = watcher.run_process_observation([sys.executable, '-c', 'import time; time.sleep(3)'], .05)
        self.assertEqual(timed['status'], 'QUERY_FAILURE')
        self.assertEqual(timed['conclusion'], 'TIMED_OUT')

    def test_watch_surfaces_native_process_exit_codes_as_query_failures(self):
        for code in (-2147483648, -1073741819, -9, 256, 3221225477, 4294967295):
            with self.subTest(code=code):
                observation = watcher._query_failure('process_exit', code)
                with patch.object(watcher, 'run_process_observation', return_value=observation) as query:
                    result = watcher.watch(['query'], timeout_seconds=1, poll_interval_seconds=.01)
                self.assertEqual(result['state'], 'failure')
                self.assertTrue(result['actionable'])
                self.assertEqual(result['observation']['exit_code'], code)
                self.assertEqual(result['observation']['failure_reason'], 'process_exit')
                query.assert_called_once()

    def test_query_exit_codes_reject_out_of_range_and_noninteger_values(self):
        for code in (-2147483649, 4294967296, True, 1.5, '7'):
            with self.subTest(code=code):
                result = watcher.parse_status_query(json.dumps(watcher._query_failure('process_exit', code)))
                self.assertEqual(result['failure_reason'], 'malformed_observation')
                self.assertNotIn('exit_code', result)

    def test_status_query_rejects_large_output_and_duplicate_json_keys(self):
        large = watcher.run_process_observation([sys.executable, '-c', 'print("x" * 2000000)'], 1)
        self.assertEqual(large['status'], 'QUERY_FAILURE')
        self.assertLess(len(json.dumps(large)), 4096)
        self.assertEqual(watcher.parse_status_query('{"status":"RUNNING","status":"COMPLETED"}')['status'], 'QUERY_FAILURE')

    def test_watch_polls_actual_queries_and_returns_only_material_change(self):
        observations = [{'status': 'RUNNING', 'logs': 'a'}, {'status': 'RUNNING', 'logs': 'b'},
                        {'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]
        with patch.object(watcher, 'run_process_observation', side_effect=observations) as query:
            result = watcher.watch(['query'], timeout_seconds=2, poll_interval_seconds=.001)
        self.assertEqual(result['state'], 'terminal')
        self.assertEqual(query.call_count, 3)
        self.assertLessEqual(query.call_args.args[1], 2)

    def test_total_deadline_caps_query_and_zero_timeout_runs_no_process(self):
        with patch.object(watcher, 'run_process_observation') as query:
            result = watcher.watch(['query'], timeout_seconds=0, poll_interval_seconds=1)
        query.assert_not_called()
        self.assertEqual(result['state'], 'timeout')
        start = time.monotonic()
        proc = subprocess.run([sys.executable, str(MODULE_PATH), '--timeout', '.12', '--process-timeout', '5',
                               '--process', sys.executable, '-c', 'import time; time.sleep(3)'], capture_output=True, timeout=2)
        self.assertLess(time.monotonic() - start, 1.5)
        result = json.loads(proc.stdout)
        self.assertEqual(result['state'], 'failure')
        self.assertEqual(result['observation']['conclusion'], 'TIMED_OUT')

    def test_invalid_duration_types_and_nonfinite_values_are_rejected(self):
        for value in (-1, True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                watcher.watch(['query'], timeout_seconds=value, poll_interval_seconds=1)
        with self.assertRaises(ValueError):
            watcher.watch(['query'], timeout_seconds=1, poll_interval_seconds=0)

    def test_mask_is_default_off_and_actually_removes_identical_success_payload(self):
        raw = success()
        self.assertEqual(watcher.apply_conditional_mask(raw, raw), raw)
        masked = watcher.apply_conditional_mask(raw, copy.deepcopy(raw), enabled=True)
        self.assertNotIn('payload', masked)
        self.assertEqual(masked['masked_from'], 'prior-success')
        self.assertLess(len(json.dumps(masked)), 1000)
        self.assertEqual(watcher.restore_mask(masked, raw), raw)

    def test_mask_recomputes_hash_and_cannot_hide_changed_or_running_payload(self):
        prior = success()
        prior['payload_sha256'] = 'f' * 64
        for update in ({'payload': {'log': 'changed'}}, {'status': 'RUNNING'},
                       {'digest': 'b' * 64}, {'conclusion': 'FAILURE'},
                       {'decision': 'required'}, {'evidence': ['current']}):
            current = {**prior, **update}
            self.assertEqual(watcher.apply_conditional_mask(current, prior, enabled=True), current)
        masked = watcher.apply_conditional_mask(prior, prior, enabled=True)
        self.assertNotEqual(masked['payload_sha256'], 'f' * 64)
        forged = {**prior, 'payload': {'log': 'different'}}
        with self.assertRaises(ValueError):
            watcher.restore_mask(masked, forged)

    def test_cli_process_reads_json_and_never_emits_raw_query_errors(self):
        proc = subprocess.run([sys.executable, str(MODULE_PATH), '--timeout', '1', '--process', sys.executable,
                               '-c', 'print(\'{"status":"COMPLETED","conclusion":"SUCCESS"}\')'], capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['state'], 'terminal')
        result = watcher.run_process_observation(['missing-command-token=canary'], 1)
        self.assertNotIn('canary', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
