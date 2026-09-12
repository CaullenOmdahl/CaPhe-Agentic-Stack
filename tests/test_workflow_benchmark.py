import copy
import unittest
from tools.benchmark_workflow import aggregate_attempts, BenchmarkError


def card():
    return {'schema_version': 1, 'date': '2026-09-12', 'currency': 'USD', 'models': {
        'frontier': {'tiers': {'standard': {'input_per_million': 1, 'cached_input_per_million': 0.1, 'output_per_million': 2}}},
        'small': {'tiers': {'standard': {'input_per_million': 0.2, 'cached_input_per_million': 0.02, 'output_per_million': 0.4}}}}}


def event(identifier='r1', **overrides):
    value = {'schema_version': 1, 'event_type': 'request_final', 'request_id': identifier,
             'task_id': 'task-1', 'repetition': 0, 'config': 'incumbent', 'model': 'frontier',
             'effort': 'high', 'service_tier': 'standard', 'parent_id': None, 'child_ids': [],
             'complete': True, 'task_final': True, 'acceptance_digest': 'a' * 64,
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


if __name__ == '__main__':
    unittest.main()
