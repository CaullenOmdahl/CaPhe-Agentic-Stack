import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tools.benchmark_workflow import aggregate_attempts, BenchmarkError, EVENT_SCHEMA


def card():
    return {'schema_version': 1, 'date': '2026-09-12', 'currency': 'USD', 'models': {
        'frontier': {'tiers': {'standard': {'input_per_million': 1, 'cached_input_per_million': 0.1, 'output_per_million': 2}}},
        'small': {'tiers': {'standard': {'input_per_million': 0.2, 'cached_input_per_million': 0.02, 'output_per_million': 0.4}}}}}


def event(identifier='r1', **overrides):
    value = {'schema_version': 1, 'event_type': 'request_final', 'request_id': identifier,
             'task_id': 'task-1', 'repetition': 0, 'config': 'incumbent', 'model': 'frontier',
             'effort': 'high', 'service_tier': 'standard', 'parent_id': None, 'child_ids': [],
             'complete': True, 'task_final': True, 'acceptance_digest': 'a' * 64,
             'task_class': 'implementation', 'source_digest': 'b' * 64, 'harness_digest': 'c' * 64,
             'usage': {'input_tokens': 1000, 'cached_input_tokens': 400, 'output_tokens': 100,
                       'reasoning_tokens': 50, 'output_includes_reasoning': True},
             'outcome': 'accepted', 'latency_ms': 1000, 'external_wait_ms': 100}
    value.update(overrides)
    return value


class BenchmarkTests(unittest.TestCase):
    def test_exact_final_event_dedup_and_request_identity_conflicts(self):
        result = aggregate_attempts([event(), event()], card())
        self.assertEqual(result['attempts_counted'], 1)
        for changed in (event(outcome='rejected'), event(event_type='cumulative'), event(attempt=2)):
            with self.assertRaises(BenchmarkError):
                aggregate_attempts([event(), changed], card())

    def test_reasoning_is_only_added_when_explicitly_excluded(self):
        included = aggregate_attempts([event()], card())
        item = event()
        item['usage']['output_includes_reasoning'] = False
        excluded = aggregate_attempts([item], card())
        self.assertEqual(included['token_totals']['output'], 100)
        self.assertEqual(excluded['token_totals']['output'], 150)
        self.assertAlmostEqual(included['spend'], 0.00084)
        self.assertAlmostEqual(excluded['spend'], 0.00094)

    def test_invalid_usage_and_metrics_reject_bool_negative_nan(self):
        for bad in (-1, True, float('nan')):
            for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens'):
                item = event()
                item['usage'][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(BenchmarkError):
                    aggregate_attempts([item], card())
            with self.assertRaises(BenchmarkError):
                aggregate_attempts([event(latency_ms=bad)], card())
        item = event()
        item['usage']['cached_input_tokens'] = 1001
        with self.assertRaises(BenchmarkError):
            aggregate_attempts([item], card())

    def test_unknown_material_usage_ineligible_without_invented_spend(self):
        for field in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'output_includes_reasoning'):
            item = event()
            item['usage'][field] = None
            result = aggregate_attempts([item], card())
            self.assertFalse(result['cost_eligible'])
            self.assertIsNone(result['spend'])
        item = event()
        item['usage']['reasoning_tokens'] = None
        self.assertTrue(aggregate_attempts([item], card())['cost_eligible'])
        item['usage']['output_includes_reasoning'] = False
        self.assertFalse(aggregate_attempts([item], card())['cost_eligible'])

    def test_absent_usage_is_unknown_not_zero_and_child_config_must_match(self):
        result = aggregate_attempts([event(usage={})], card())
        self.assertFalse(result['cost_eligible'])
        self.assertEqual(result['token_totals']['input'], None)
        with self.assertRaises(BenchmarkError):
            aggregate_attempts([event(child_ids=['child']),
                event('child', parent_id='r1', task_final=False, config='different')], card())

    def test_required_identity_must_be_nonempty_and_typed(self):
        for field in ('request_id', 'task_id', 'config', 'model', 'effort', 'service_tier'):
            for value in (None, '', 1):
                with self.subTest(field=field, value=value), self.assertRaises(BenchmarkError):
                    aggregate_attempts([event(**{field: value})], card())
        with self.assertRaises(BenchmarkError):
            aggregate_attempts([event(repetition=True)], card())

    def test_charge_all_retry_and_child_spend_count_only_final_root_task(self):
        attempt = event('retry-1', task_final=False, outcome='rejected')
        final = event('final-1', child_ids=['child-1'])
        child = event('child-1', parent_id='final-1', task_final=False, model='small')
        result = aggregate_attempts([attempt, final, child], card())
        self.assertEqual(result['attempts_counted'], 3)
        self.assertEqual(result['accepted_tasks'], 1)
        self.assertEqual(result['root_tasks_counted'], 1)
        self.assertAlmostEqual(result['spend'], 0.001848)
        self.assertEqual(set(result['spend_by_config_model']['incumbent']), {'frontier', 'small'})

    def test_missing_parent_child_incomplete_or_root_final_blocks_closure(self):
        invalid = [[event(child_ids=['missing'])], [event(parent_id='missing', task_final=False)],
                   [event(complete=False)], [event(task_final=False)],
                   [event(child_ids=['child']), event('child', parent_id='r1', task_final=False, complete=False)]]
        for events in invalid:
            with self.subTest(events=events):
                result = aggregate_attempts(events, card())
                self.assertFalse(result['cost_eligible'])
                self.assertEqual(result['accepted_tasks'], 0)
                self.assertEqual(result['quality_deltas']['status'], 'inconclusive')

    def test_cycles_and_inconsistent_child_declarations_rejected(self):
        invalid = [[event(child_ids=['child']), event('child', parent_id='different', task_final=False)],
                   [event(parent_id='child', child_ids=['child'], task_final=False),
                    event('child', parent_id='r1', child_ids=['r1'], task_final=False)],
                   [event(), event('second-final')]]
        for events in invalid:
            with self.assertRaises(BenchmarkError):
                aggregate_attempts(events, card())

    def test_missing_model_or_tier_rates_ineligible_and_bad_rates_reject(self):
        for item in (event(model='unpriced'), event(service_tier='unknown')):
            result = aggregate_attempts([item], card())
            self.assertFalse(result['cost_eligible'])
            self.assertIsNone(result['spend'])
        for invalid in (float('nan'), -1, True):
            rates = card()
            rates['models']['frontier']['tiers']['standard']['input_per_million'] = invalid
            with self.assertRaises(BenchmarkError):
                aggregate_attempts([event()], rates)
        rates = card()
        rates['models']['small']['currency'] = 'EUR'
        with self.assertRaises(BenchmarkError):
            aggregate_attempts([event()], rates)

    def test_quality_is_paired_root_task_delta_not_configuration_mean(self):
        events = [event('base-1'), event('candidate-1', config='candidate', outcome='rejected'),
                  event('base-2', task_id='task-2', outcome='rejected'),
                  event('candidate-2', task_id='task-2', config='candidate', outcome='accepted')]
        result = aggregate_attempts(events, card())
        self.assertEqual(result['quality_deltas']['status'], 'computed')
        comparison = result['quality_deltas']['comparisons']['candidate']
        self.assertEqual(comparison['paired_tasks'], 2)
        self.assertEqual(comparison['delta'], 0)
        self.assertEqual((comparison['wins'], comparison['losses']), (1, 1))
        events[-1]['acceptance_digest'] = 'b' * 64
        self.assertEqual(aggregate_attempts(events, card())['quality_deltas']['status'], 'inconclusive')

    def test_unpaired_or_incomplete_repetitions_are_inconclusive(self):
        for candidate in (event('candidate', config='candidate', repetition=1),
                          event('candidate', config='candidate', complete=False)):
            result = aggregate_attempts([event(), candidate], card())
            self.assertEqual(result['quality_deltas']['status'], 'inconclusive')

    def test_quality_rejects_config_route_changes_across_tasks_and_repetitions(self):
        rates = card()
        rates['models']['frontier']['tiers']['priority'] = copy.deepcopy(
            rates['models']['frontier']['tiers']['standard'])
        for field, value in (('model', 'small'), ('effort', 'medium'), ('service_tier', 'priority')):
            for changed_config in ('incumbent', 'candidate'):
                for next_trial in ({'task_id': 'task-2'}, {'repetition': 1}):
                    with self.subTest(field=field, config=changed_config, next_trial=next_trial):
                        events = [event('base-0'), event('candidate-0', config='candidate'),
                                  event('base-1', **next_trial),
                                  event('candidate-1', config='candidate', **next_trial)]
                        changed = events[2 if changed_config == 'incumbent' else 3]
                        changed[field] = value
                        result = aggregate_attempts(events, rates)
                        self.assertEqual(result['quality_deltas']['status'], 'inconclusive')
                        self.assertEqual(result['quality_deltas']['reason'], 'mixed_config_routes')
                        self.assertTrue(result['cost_eligible'])
                        self.assertEqual(result['attempts_counted'], 4)
                        self.assertIsNotNone(result['spend'])

    def test_quality_rejects_mixed_retry_and_child_routes_without_dropping_spend(self):
        rates = card()
        rates['models']['frontier']['tiers']['priority'] = copy.deepcopy(
            rates['models']['frontier']['tiers']['standard'])
        for field, value in (('model', 'small'), ('effort', 'medium'), ('service_tier', 'priority')):
            for kind in ('retry', 'child'):
                with self.subTest(field=field, kind=kind):
                    final = event('candidate', config='candidate')
                    extra = event('extra', config='candidate', task_final=False, **{field: value})
                    if kind == 'child':
                        final['child_ids'] = ['extra']
                        extra['parent_id'] = 'candidate'
                    result = aggregate_attempts([event(), final, extra], rates)
                    self.assertEqual(result['quality_deltas']['status'], 'inconclusive')
                    self.assertEqual(result['quality_deltas']['reason'], 'mixed_config_routes')
                    self.assertTrue(result['cost_eligible'])
                    self.assertEqual(result['attempts_counted'], 3)
                    self.assertEqual(result['root_tasks_counted'], 2)
                    expected = 0.001848 if field == 'model' else 0.00252
                    self.assertAlmostEqual(result['spend'], expected)

    def test_quality_compares_distinct_stable_config_routes(self):
        rates = card()
        rates['models']['small']['tiers']['priority'] = copy.deepcopy(
            rates['models']['small']['tiers']['standard'])
        events = []
        for repetition in (0, 1):
            events.extend([event('base-' + str(repetition), repetition=repetition),
                           event('candidate-' + str(repetition), repetition=repetition,
                                 config='candidate', model='small', effort='medium',
                                 service_tier='priority')])
        result = aggregate_attempts(events, rates)
        self.assertEqual(result['quality_deltas']['status'], 'computed')
        self.assertEqual(result['quality_deltas']['comparisons']['candidate']['paired_runs'], 2)
        self.assertTrue(result['cost_eligible'])

    def test_legacy_and_partial_bindings_preserve_cost_but_cannot_compare_quality(self):
        fields = ('task_class', 'source_digest', 'harness_digest')
        for missing in (fields, *[(field,) for field in fields]):
            with self.subTest(missing=missing):
                events = [event(), event('candidate', config='candidate')]
                for item in events:
                    for field in missing:
                        del item[field]
                result = aggregate_attempts(events, card())
                self.assertEqual(result['quality_deltas']['status'], 'inconclusive')
                self.assertEqual(result['quality_deltas']['reason'], 'missing_quality_bindings')
                self.assertTrue(result['cost_eligible'])
                self.assertAlmostEqual(result['spend'], 0.00168)
                self.assertEqual(result['accepted_tasks'], 2)

    def test_mixed_task_classes_cannot_mask_implementation_losses_with_lookup_wins(self):
        events = [event('base-lookup', task_id='lookup', task_class='lookup', outcome='rejected'),
                  event('candidate-lookup', task_id='lookup', task_class='lookup', config='candidate'),
                  event('base-implementation', task_id='implementation'),
                  event('candidate-implementation', task_id='implementation', config='candidate', outcome='rejected')]
        result = aggregate_attempts(events, card())
        self.assertEqual(result['quality_deltas'], {'status': 'inconclusive', 'reason': 'mixed_task_classes'})
        self.assertTrue(result['cost_eligible'])
        implementation = aggregate_attempts(events[2:], card())['quality_deltas']
        self.assertEqual(implementation['task_class'], 'implementation')
        self.assertEqual(implementation['comparisons']['candidate']['delta'], -1)

    def test_paired_task_and_repetition_require_identical_source_and_harness(self):
        for field in ('source_digest', 'harness_digest'):
            for repetition in (0, 1):
                with self.subTest(field=field, repetition=repetition):
                    events = [event('base-0'), event('candidate-0', config='candidate'),
                              event('base-1', repetition=1),
                              event('candidate-1', repetition=1, config='candidate')]
                    events[1 if repetition == 0 else 3][field] = 'd' * 64
                    result = aggregate_attempts(events, card())
                    self.assertEqual(result['quality_deltas'],
                                     {'status': 'inconclusive', 'reason': 'evaluation_binding_mismatch'})
                    self.assertTrue(result['cost_eligible'])

    def test_retry_and_child_requests_cannot_hide_unbound_or_changed_evaluation_inputs(self):
        for kind in ('retry', 'child'):
            for field, reason in (('task_class', 'mixed_task_classes'),
                    ('source_digest', 'evaluation_binding_mismatch'),
                    ('harness_digest', 'evaluation_binding_mismatch')):
                for missing in (False, True):
                    with self.subTest(kind=kind, field=field, missing=missing):
                        final = event('candidate', config='candidate')
                        extra = event('extra', config='candidate', task_final=False)
                        if kind == 'child':
                            final['child_ids'] = ['extra']; extra['parent_id'] = 'candidate'
                        if missing:
                            del extra[field]
                        else:
                            extra[field] = 'lookup' if field == 'task_class' else 'd' * 64
                        result = aggregate_attempts([event(), final, extra], card())
                        self.assertEqual(result['quality_deltas'], {'status': 'inconclusive',
                            'reason': 'missing_quality_bindings' if missing else reason})
                        self.assertTrue(result['cost_eligible'])
                        self.assertAlmostEqual(result['spend'], 0.00252)

    def test_computed_report_exposes_exact_per_pair_bindings_and_one_class(self):
        events = [event(), event('candidate-0', config='candidate'),
                  event('base-1', repetition=1, source_digest='d' * 64, harness_digest='e' * 64),
                  event('candidate-1', repetition=1, config='candidate', source_digest='d' * 64, harness_digest='e' * 64)]
        quality = aggregate_attempts(events, card())['quality_deltas']
        self.assertEqual(quality['status'], 'computed')
        self.assertEqual(quality['task_class'], 'implementation')
        self.assertEqual(quality['evaluation_bindings'], [
            {'task_id': 'task-1', 'repetition': 0, 'source_digest': 'b' * 64,
             'harness_digest': 'c' * 64, 'acceptance_digest': 'a' * 64},
            {'task_id': 'task-1', 'repetition': 1, 'source_digest': 'd' * 64,
             'harness_digest': 'e' * 64, 'acceptance_digest': 'a' * 64}])

    def test_optional_quality_bindings_are_closed_and_match_routing_syntax(self):
        from tools.stack_route import ID, DIGEST
        self.assertEqual(EVENT_SCHEMA['properties']['task_class'], ID)
        for field in ('source_digest', 'harness_digest'):
            self.assertEqual(EVENT_SCHEMA['properties'][field], DIGEST)
        for field in ('task_class', 'source_digest', 'harness_digest'):
            self.assertNotIn(field, EVENT_SCHEMA['required'])
            for value in (None, True, 1, '', 'invalid value', 'A' * 64, '../path'):
                if field == 'task_class' and value == 'A' * 64:
                    continue  # Uppercase identifiers are valid in the routing contract.
                with self.subTest(field=field, value=value), self.assertRaises(BenchmarkError):
                    aggregate_attempts([event(**{field: value})], card())

    def test_quality_requires_same_acceptance_across_all_repetitions_of_each_task(self):
        events = [event('base-0'), event('candidate-0', config='candidate'),
                  event('base-1', repetition=1, acceptance_digest='b' * 64),
                  event('candidate-1', config='candidate', repetition=1, acceptance_digest='b' * 64)]
        result = aggregate_attempts(events, card())
        self.assertEqual(result['quality_deltas']['status'], 'inconclusive')
        self.assertTrue(result['cost_eligible'])
        for item in events:
            item['acceptance_digest'] = 'a' * 64
        stable = aggregate_attempts(events, card())
        self.assertEqual(stable['quality_deltas']['status'], 'computed')
        self.assertEqual(stable['quality_deltas']['comparisons']['candidate']['paired_tasks'], 1)
        self.assertEqual(stable['quality_deltas']['comparisons']['candidate']['paired_runs'], 2)

    def test_quality_weights_tasks_equally_when_repetition_counts_differ(self):
        events = []
        for task, repetitions in (('winning-task', 10), ('losing-task', 1)):
            for repetition in range(repetitions):
                for config in ('incumbent', 'candidate'):
                    accepted = (task == 'winning-task') == (config == 'candidate')
                    events.append(event(task+'-'+config+'-'+str(repetition), task_id=task,
                                        repetition=repetition, config=config,
                                        outcome='accepted' if accepted else 'rejected'))
        comparison = aggregate_attempts(events, card())['quality_deltas']['comparisons']['candidate']
        self.assertEqual(comparison['paired_tasks'], 2)
        self.assertEqual(comparison['paired_runs'], 11)
        self.assertEqual(comparison['repetitions_per_task'], {'winning-task': 10, 'losing-task': 1})
        self.assertEqual(comparison['delta'], 0)
        self.assertEqual((comparison['wins'], comparison['losses'], comparison['ties']), (1, 1, 0))

    def test_mixed_repetitions_count_task_level_acceptance_rate_direction(self):
        events = [event('base-0'), event('candidate-0', config='candidate', outcome='rejected'),
                  event('base-1', repetition=1, outcome='rejected'),
                  event('candidate-1', config='candidate', repetition=1)]
        comparison = aggregate_attempts(events, card())['quality_deltas']['comparisons']['candidate']
        self.assertEqual(comparison['paired_tasks'], 1)
        self.assertEqual(comparison['paired_runs'], 2)
        self.assertEqual(comparison['delta'], 0)
        self.assertEqual((comparison['wins'], comparison['losses'], comparison['ties']), (0, 0, 1))

    def test_root_latency_and_external_wait_reported_separately(self):
        result = aggregate_attempts([event(latency_ms=2000, external_wait_ms=500)], card())
        self.assertEqual(result['latency_ms']['external_wait_median'], 500)
        self.assertEqual(result['latency_ms']['median'], 2000)


class BenchmarkCliTests(unittest.TestCase):
    def run_cli(self, events_json, card_json):
        with tempfile.TemporaryDirectory() as directory:
            rates = Path(directory) / 'rates.json'
            rates.write_text(card_json, encoding='utf-8')
            return subprocess.run([sys.executable,
                str(Path(__file__).resolve().parents[1] / 'tools/benchmark_workflow.py'),
                '--card', str(rates)], input=events_json, cwd=directory,
                capture_output=True, text=True, timeout=10)

    def assert_duplicate_rejected(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('benchmark rejected: duplicate keys', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_cli_rejects_duplicate_event_keys_including_nested_usage(self):
        encoded = json.dumps(event())
        cases = [encoded[:-1] + ', "outcome": "rejected"}',
                 json.dumps(event(outcome='rejected'))[:-1] + ', "outcome": "accepted"}',
                 encoded.replace('"input_tokens": 1000',
                                 '"input_tokens": 2000, "input_tokens": 1000')]
        for events_json in cases:
            with self.subTest(events_json=events_json):
                self.assert_duplicate_rejected(self.run_cli(events_json, json.dumps(card())))

    def test_cli_rejects_duplicate_rate_card_keys_including_nested_rates(self):
        encoded = json.dumps(card())
        cases = [encoded[:-1] + ', "currency": "EUR"}',
                 encoded.replace('"input_per_million": 1',
                                 '"input_per_million": 10, "input_per_million": 1', 1)]
        for card_json in cases:
            with self.subTest(card_json=card_json):
                self.assert_duplicate_rejected(self.run_cli(json.dumps(event()), card_json))

    def test_cli_accepts_unique_event_and_rate_card_keys(self):
        result = self.run_cli(json.dumps(event()) + '\n', json.dumps(card()))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = json.loads(result.stdout)
        self.assertEqual(result['accepted_tasks'], 1)
        self.assertAlmostEqual(result['spend'], 0.00084)


if __name__ == '__main__':
    unittest.main()
