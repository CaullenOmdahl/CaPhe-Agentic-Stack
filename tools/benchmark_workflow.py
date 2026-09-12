"""Account final request events and compare paired, closed root-task outcomes.

Request usage is incremental per request, never a cumulative conversation counter.
Retries use new request IDs; only one root request closes each task/config/repetition.
Children retain that evaluated task identity and declare their parent request ID.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from decimal import Decimal
import json
import math
import re
from statistics import median
import sys


class BenchmarkError(ValueError):
    pass


ID = {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'}
TOKEN = {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 10**12}
MEASURE = {'type': ['number', 'null'], 'minimum': 0, 'maximum': 10**12}
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens', 'output_includes_reasoning')
EVENT_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object', 'additionalProperties': False,
    'properties': {
        'schema_version': {'const': 1}, 'event_type': {'const': 'request_final'},
        **{field: ID for field in ('request_id', 'task_id', 'config', 'model', 'effort', 'service_tier')},
        'repetition': {'type': 'integer', 'minimum': 0},
        'parent_id': {'type': ['string', 'null'], 'pattern': ID['pattern']},
        'child_ids': {'type': 'array', 'items': ID, 'uniqueItems': True},
        'complete': {'type': 'boolean'}, 'task_final': {'type': 'boolean'},
        'acceptance_digest': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        'usage': {'type': 'object', 'additionalProperties': False, 'properties': {
            **{field: TOKEN for field in USAGE_FIELDS[:-1]}, 'output_includes_reasoning': {'type': ['boolean', 'null']}}},
        'outcome': {'enum': ['accepted', 'rejected', 'blocked', 'unknown']},
        'latency_ms': MEASURE, 'external_wait_ms': MEASURE,
    },
}
EVENT_SCHEMA['required'] = list(EVENT_SCHEMA['properties'])
RATE_FIELDS = ('input_per_million', 'cached_input_per_million', 'output_per_million')


def _closed(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - set(value) or set(value) - set(required) - set(optional):
        raise BenchmarkError('missing or unknown fields')


def _id(value):
    if not isinstance(value, str) or re.fullmatch(ID['pattern'], value) is None:
        raise BenchmarkError('identity must be a nonempty identifier')


def _number(value, integer=False, nullable=False):
    if value is None and nullable:
        return
    if (type(value) is not int if integer else type(value) not in (int, float)):
        raise BenchmarkError('numeric values must not be booleans or strings')
    if not math.isfinite(value) or not 0 <= value <= 10**12:
        raise BenchmarkError('numeric values must be finite and nonnegative')


def validate_event(event):
    _closed(event, EVENT_SCHEMA['required'])
    if type(event['schema_version']) is not int or event['schema_version'] != 1 or event['event_type'] != 'request_final':
        raise BenchmarkError('only version 1 per-request final events are accepted; normalize cumulative streams first')
    for field in ('request_id', 'task_id', 'config', 'model', 'effort', 'service_tier'):
        _id(event[field])
    _number(event['repetition'], integer=True)
    if event['parent_id'] is not None:
        _id(event['parent_id'])
    if not isinstance(event['child_ids'], list):
        raise BenchmarkError('declared children must be a list')
    for child in event['child_ids']:
        _id(child)
    if len(set(event['child_ids'])) != len(event['child_ids']) or event['request_id'] in event['child_ids']:
        raise BenchmarkError('duplicate/self child declarations')
    for field in ('complete', 'task_final'):
        if type(event[field]) is not bool:
            raise BenchmarkError(field + ' must be boolean')
    if event['task_final'] and event['parent_id'] is not None:
        raise BenchmarkError('child requests cannot declare root task completion')
    if not isinstance(event['acceptance_digest'], str) or re.fullmatch(r'[0-9a-f]{64}', event['acceptance_digest']) is None:
        raise BenchmarkError('acceptance must have a stable SHA-256 binding')
    if event['outcome'] not in ('accepted', 'rejected', 'blocked', 'unknown'):
        raise BenchmarkError('invalid outcome')
    usage = event['usage']
    _closed(usage, [], USAGE_FIELDS)
    for field in USAGE_FIELDS[:-1]:
        _number(usage.get(field), integer=True, nullable=True)
    includes = usage.get('output_includes_reasoning')
    if includes is not None and type(includes) is not bool:
        raise BenchmarkError('output_includes_reasoning must be boolean or unknown')
    inputs, cached = usage.get('input_tokens'), usage.get('cached_input_tokens')
    outputs, reasoning = usage.get('output_tokens'), usage.get('reasoning_tokens')
    if inputs is not None and cached is not None and cached > inputs:
        raise BenchmarkError('cached input cannot exceed total input')
    if includes is True and outputs is not None and reasoning is not None and reasoning > outputs:
        raise BenchmarkError('included reasoning cannot exceed total output')
    for field in ('latency_ms', 'external_wait_ms'):
        _number(event[field], nullable=True)
    if event['latency_ms'] is not None and event['external_wait_ms'] is not None and event['external_wait_ms'] > event['latency_ms']:
        raise BenchmarkError('external wait cannot exceed request wall time')


def validate_rate_card(card):
    _closed(card, ['schema_version', 'date', 'currency', 'models'])
    if type(card['schema_version']) is not int or card['schema_version'] != 1:
        raise BenchmarkError('unsupported rate card version')
    if not isinstance(card['date'], str):
        raise BenchmarkError('rate card needs an ISO date')
    try:
        parsed = date.fromisoformat(card['date'])
    except ValueError as error:
        raise BenchmarkError('rate card needs an ISO date') from error
    if parsed.isoformat() != card['date'] or not isinstance(card['currency'], str) or re.fullmatch('[A-Z]{3}', card['currency']) is None:
        raise BenchmarkError('rate card date/currency is invalid')
    if not isinstance(card['models'], dict):
        raise BenchmarkError('rate card requires per-model rates')
    for model, settings in card['models'].items():
        _id(model)
        _closed(settings, ['tiers'])
        if not isinstance(settings['tiers'], dict):
            raise BenchmarkError('model rates require explicit service tiers')
        for tier, rates in settings['tiers'].items():
            _id(tier)
            _closed(rates, RATE_FIELDS)
            for rate in rates.values():
                _number(rate)


def _key(event):
    return event['config'], event['task_id'], event['repetition']


def _tokens(event):
    usage = event['usage']
    inputs, cached = usage.get('input_tokens'), usage.get('cached_input_tokens')
    outputs, reasoning = usage.get('output_tokens'), usage.get('reasoning_tokens')
    includes = usage.get('output_includes_reasoning')
    uncached = inputs - cached if inputs is not None and cached is not None else None
    billed_output = outputs if includes is True else (
        outputs + reasoning if includes is False and outputs is not None and reasoning is not None else None)
    return {'input': uncached, 'cached_input': cached, 'output': billed_output}


def _closure(events):
    """Validate graph consistency and return root evaluation runs with closure flags."""
    groups = defaultdict(list)
    incomplete = defaultdict(set)
    for event in events.values():
        key = _key(event)
        groups[key].append(event)
        if not event['complete']:
            incomplete[key].add('request_not_complete')
        parent = event['parent_id']
        if parent is not None:
            if parent not in events:
                incomplete[key].add('missing_parent')
            else:
                ancestor = events[parent]
                if event['request_id'] not in ancestor['child_ids'] or _key(ancestor) != key or ancestor['acceptance_digest'] != event['acceptance_digest']:
                    raise BenchmarkError('parent/child declaration or evaluation identity mismatch')
        for child in event['child_ids']:
            if child not in events:
                incomplete[key].add('missing_child')
            elif events[child]['parent_id'] != event['request_id']:
                raise BenchmarkError('declared child has a different parent')
    for identifier in events:
        visited = set()
        cursor = identifier
        while cursor in events:
            if cursor in visited:
                raise BenchmarkError('cyclic request graph')
            visited.add(cursor)
            cursor = events[cursor]['parent_id']
    trials = {}
    for key, group in groups.items():
        finals = [event for event in group if event['task_final']]
        if len(finals) > 1:
            raise BenchmarkError('multiple final root outcomes for one task/config/repetition')
        if not finals:
            incomplete[key].add('missing_final_root_outcome')
        if len({event['acceptance_digest'] for event in group}) != 1:
            raise BenchmarkError('retry/child acceptance contract changed within a trial')
        final = finals[0] if finals else None
        if final and final['outcome'] in ('blocked', 'unknown'):
            incomplete[key].add('unknown_terminal_outcome')
        trials[key] = {'events': group, 'final': final, 'complete': not incomplete[key],
                       'reasons': sorted(incomplete[key])}
    return trials


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _quality(trials, incumbent):
    configurations = sorted({key[0] for key in trials})
    if incumbent not in configurations or len(configurations) < 2:
        return {'status': 'inconclusive', 'reason': 'paired incumbent and candidate runs are required'}
    if any(not trial['complete'] for trial in trials.values()):
        return {'status': 'inconclusive', 'reason': 'request/task closure is incomplete'}
    # A config label alone cannot bind a composite workflow policy. Include
    # retries and children so route changes cannot hide behind a stable final root.
    routes = defaultdict(set)
    for (config, _, _), trial in trials.items():
        for event in trial['events']:
            routes[config].add((event['model'], event['effort'], event['service_tier']))
    if any(len(values) != 1 for values in routes.values()):
        return {'status': 'inconclusive', 'reason': 'mixed_config_routes'}
    acceptance_by_task = {}
    for (_, task, _), trial in trials.items():
        digest = trial['final']['acceptance_digest']
        if task in acceptance_by_task and acceptance_by_task[task] != digest:
            return {'status': 'inconclusive', 'reason': 'task acceptance changed across repetitions or configurations'}
        acceptance_by_task[task] = digest
    reference = {(task, repetition): trial for (config, task, repetition), trial in trials.items() if config == incumbent}
    comparisons = {}
    for config in configurations:
        if config == incumbent:
            continue
        candidate = {(task, repetition): trial for (name, task, repetition), trial in trials.items() if name == config}
        if candidate.keys() != reference.keys():
            return {'status': 'inconclusive', 'reason': 'task/repetition sets are not paired'}
        by_task = defaultdict(list)
        for key, trial in candidate.items():
            left, right = reference[key]['final'], trial['final']
            if left['acceptance_digest'] != right['acceptance_digest']:
                return {'status': 'inconclusive', 'reason': 'paired acceptance contracts differ'}
            by_task[key[0]].append(int(right['outcome'] == 'accepted') - int(left['outcome'] == 'accepted'))
        # Repetitions estimate a task's acceptance rate; they do not give that
        # task greater weight than other tasks in the evaluation set.
        differences = [sum(values) / len(values) for values in by_task.values()]
        comparisons[config] = {'paired_tasks': len(by_task), 'paired_runs': len(candidate),
                               'repetitions_per_task': {task: len(by_task[task]) for task in sorted(by_task)},
                               'delta': sum(differences) / len(differences),
                               'wins': sum(value > 0 for value in differences),
                               'losses': sum(value < 0 for value in differences),
                               'ties': differences.count(0)}
    return {'status': 'computed', 'incumbent': incumbent, 'comparisons': comparisons,
            'interpretation': 'equal task weights with repetitions averaged within each task; descriptive acceptance-rate deltas, not statistical non-inferiority'}


def aggregate_attempts(events, card, incumbent_config='incumbent'):
    validate_rate_card(card)
    _id(incumbent_config)
    unique = {}
    for event in events:
        validate_event(event)
        identifier = event['request_id']
        if identifier in unique:
            if json.dumps(unique[identifier], sort_keys=True) != json.dumps(event, sort_keys=True):
                raise BenchmarkError('conflicting duplicate request final event')
        else:
            unique[identifier] = event
    trials = _closure(unique)
    observed = Decimal(0)
    reasons = set()
    breakdown = defaultdict(lambda: defaultdict(lambda: {'observed_spend': Decimal(0), 'eligible': True, 'requests': 0}))
    token_rows = []
    for event in unique.values():
        tokens = _tokens(event)
        token_rows.append(tokens)
        item = breakdown[event['config']][event['model']]
        item['requests'] += 1
        eligible = all(value is not None for value in tokens.values())
        if not eligible:
            reasons.add('unknown_material_usage')
        rates = card['models'].get(event['model'], {}).get('tiers', {}).get(event['service_tier'])
        if rates is None:
            eligible = False
            reasons.add('missing_model_or_service_tier_rate')
        trial = trials[_key(event)]
        if not trial['complete']:
            item['eligible'] = False
            reasons.update(trial['reasons'])
        item['eligible'] = item['eligible'] and eligible
        if eligible:
            cost = sum(Decimal(tokens[token]) * Decimal(str(rates[rate])) for token, rate in
                       [('input', 'input_per_million'), ('cached_input', 'cached_input_per_million'), ('output', 'output_per_million')]) / Decimal(1_000_000)
            observed += cost
            item['observed_spend'] += cost
    accepted = sum(trial['complete'] and trial['final']['outcome'] == 'accepted' for trial in trials.values())
    eligible = bool(unique) and not reasons
    spend = float(observed) if eligible else None
    totals = {key: (sum(row[key] for row in token_rows) if all(row[key] is not None for row in token_rows) else None)
              for key in ('input', 'cached_input', 'output')}
    by_config = {}
    for config, models in breakdown.items():
        by_config[config] = {}
        for model, item in models.items():
            by_config[config][model] = {'requests': item['requests'], 'observed_spend': float(item['observed_spend']),
                                       'spend': float(item['observed_spend']) if item['eligible'] else None,
                                       'cost_eligible': item['eligible'], 'currency': card['currency']}
    # Final-root request duration is not fabricated into end-to-end task duration;
    # requests can overlap, and retry sequencing is absent from this event schema.
    finals = [trial['final'] for trial in trials.values() if trial['complete']]
    latency = [event['latency_ms'] for event in finals if event['latency_ms'] is not None]
    wait = [event['external_wait_ms'] for event in finals if event['external_wait_ms'] is not None]
    efforts = sorted({event['effort'] for event in unique.values()})
    return {'attempts_counted': len(unique), 'root_tasks_counted': sum(trial['complete'] for trial in trials.values()),
            'accepted_tasks': accepted, 'accepted_task_runs': accepted,
            'spend': spend, 'observed_spend': float(observed),
            'spend_per_accepted': spend / accepted if spend is not None and accepted else None,
            'cost_eligible': eligible, 'ineligibility_reasons': sorted(reasons) if unique else ['no_events'],
            'spend_by_config_model': by_config, 'token_totals': totals,
            'reported_output_tokens': (sum(event['usage']['output_tokens'] for event in unique.values())
                                       if all(event['usage'].get('output_tokens') is not None for event in unique.values()) else None),
            'reasoning_tokens': (sum(event['usage']['reasoning_tokens'] for event in unique.values())
                                 if all(event['usage'].get('reasoning_tokens') is not None for event in unique.values()) else None),
            'efforts': efforts, 'effort_changes': len(efforts) > 1,
            'latency_ms': {'scope': 'final_root_request_only', 'median': median(latency) if latency else None,
                           'p95': _percentile(latency, .95), 'external_wait_median': median(wait) if wait else None,
                           'external_wait_p95': _percentile(wait, .95)},
            'quality_deltas': _quality(trials, incumbent_config),
            'rate_card': {'date': card['date'], 'currency': card['currency']}}


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkError('duplicate keys in benchmark JSON')
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', required=True)
    parser.add_argument('--incumbent', default='incumbent')
    args = parser.parse_args()
    try:
        with open(args.card, encoding='utf-8') as handle:
            card = json.load(handle, object_pairs_hook=_unique_json_object)
        events = [json.loads(line, object_pairs_hook=_unique_json_object)
                  for line in sys.stdin if line.strip()]
        print(json.dumps(aggregate_attempts(events, card, args.incumbent), sort_keys=True, allow_nan=False))
    except (BenchmarkError, ValueError, TypeError, OSError) as error:
        parser.exit(2, f'benchmark rejected: {error}\n')


if __name__ == '__main__':
    main()
