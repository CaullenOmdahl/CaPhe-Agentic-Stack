"""Resolve explicit routes from declared owner policy and observed capabilities.

Approval metadata binds a route to its evaluation reference. It is not a signature
or proof that external approval happened; callers must supply trusted owner policy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
import sys


class RouteError(ValueError):
    pass


ID = {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 2000}
DIGEST = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra']


def _object(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


def _list(item, minimum=0, maximum=50):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': maximum, 'uniqueItems': True}


CONTRACT_SCHEMA = {'$schema': 'https://json-schema.org/draft/2020-12/schema', **_object({
    'schema_version': {'const': 1},
    'source': _object({'repository': {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$'},
                       'revision': {'type': 'string', 'pattern': r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$'}, 'snapshot_digest': DIGEST}),
    'goal': TEXT, 'acceptance': _list(TEXT, 1), 'allowed_writes': _list(TEXT), 'exclusions': _list(TEXT),
    'lane': {'enum': ['mechanically-proven', 'scoped-behavior', 'full-risk']},
    'canon_refs': _list(TEXT, 1), 'required_checks': _list(TEXT, 1),
    'output_limits': _object({'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 65536},
                              'max_words': {'type': 'integer', 'minimum': 1, 'maximum': 2000}}),
    'repair_budget': _object({'max_repairs': {'type': 'integer', 'minimum': 0, 'maximum': 1}}),
    'escalation': {'const': 'parent'}, 'task_class': ID, 'parent_id': ID,
    'canonical_review_role': {'type': 'boolean'},
    'max_workers': {'type': 'integer', 'minimum': 0, 'maximum': 2},
    'children': _list(_object({'task_id': ID, 'goal': TEXT, 'acceptance': _list(TEXT, 1), 'allowed_writes': _list(TEXT)}), 0, 2),
}, ['schema_version', 'source', 'goal', 'acceptance', 'allowed_writes', 'exclusions', 'lane', 'canon_refs',
    'required_checks', 'output_limits', 'repair_budget', 'escalation', 'task_class', 'parent_id', 'children', 'max_workers'])}
ROUTE_SCHEMA = _object({'config': ID, 'model': ID, 'effort': {'enum': EFFORTS}, 'service_tier': ID})
APPROVAL_SCHEMA = _object({'approved': {'type': 'boolean'}, 'task_class': ID, 'config': ID,
                           'route_digest': DIGEST,
                           'evidence': _object({'id': ID, 'source_digest': DIGEST, 'acceptance_digest': DIGEST})})
CAPABILITY_SCHEMA = _object({'available': {'type': 'boolean'}, 'efforts': _list({'enum': EFFORTS}, 1),
                             'service_tiers': _list(ID, 1)})


def _validate(value, schema, name):
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise RouteError(name + ': invalid constant')
    if 'enum' in schema and value not in schema['enum']:
        raise RouteError(name + ': unsupported value')
    kind = schema.get('type')
    if kind == 'object':
        if not isinstance(value, dict) or set(value) - set(schema['properties']) or set(schema['required']) - set(value):
            raise RouteError(name + ': missing or unknown fields')
        for key, item in value.items():
            _validate(item, schema['properties'][key], name + '.' + key)
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 1) <= len(value) <= schema.get('maxLength', 2000) or not value.strip():
            raise RouteError(name + ': invalid string')
        if any(ord(char) < 32 for char in value) or ('pattern' in schema and re.fullmatch(schema['pattern'], value) is None):
            raise RouteError(name + ': invalid format')
    elif kind == 'integer':
        if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
            raise RouteError(name + ': invalid integer')
    elif kind == 'boolean' and type(value) is not bool:
        raise RouteError(name + ': expected boolean')
    elif kind == 'array':
        if not isinstance(value, list) or not schema['minItems'] <= len(value) <= schema['maxItems']:
            raise RouteError(name + ': invalid array')
        for item in value:
            _validate(item, schema['items'], name + '[]')
        if len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise RouteError(name + ': duplicate entries')


def _closed(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - set(value) or set(value) - set(required) - set(optional):
        raise RouteError('missing or unknown configuration fields')


def _path(value):
    trimmed = value.removesuffix('/')
    path = PurePosixPath(trimmed)
    if (not trimmed or path.is_absolute() or '\\' in value or ':' in value or
            any(part in ('', '.', '..', '.git', '.ssh') for part in trimmed.split('/'))):
        raise RouteError('contract paths must be explicit relative paths without traversal')


def validate_contract(contract):
    _validate(contract, CONTRACT_SCHEMA, 'contract')
    if len(contract['children']) > contract['max_workers']:
        raise RouteError('children exceed declared concurrency limit')
    ids = [child['task_id'] for child in contract['children']]
    if len(set(ids)) != len(ids) or contract['parent_id'] in ids:
        raise RouteError('child identities must be distinct from each other and their parent')
    for key in ('allowed_writes', 'exclusions', 'canon_refs'):
        for value in contract[key]:
            _path(value)
    for child in contract['children']:
        for value in child['allowed_writes']:
            _path(value)
            target = PurePosixPath(value)
            if not any(target == PurePosixPath(parent) or PurePosixPath(parent) in target.parents for parent in contract['allowed_writes']):
                raise RouteError('child writes exceed parent scope')
    for index, child in enumerate(contract['children']):
        for other in contract['children'][index + 1:]:
            for left in map(PurePosixPath, child['allowed_writes']):
                for right in map(PurePosixPath, other['allowed_writes']):
                    if left == right or left in right.parents or right in left.parents:
                        raise RouteError('child write scopes must be disjoint')
    for value in contract['allowed_writes'] + [path for child in contract['children'] for path in child['allowed_writes']]:
        target = PurePosixPath(value)
        if any(target == PurePosixPath(exclusion) or PurePosixPath(exclusion) in target.parents for exclusion in contract['exclusions']):
            raise RouteError('allowed writes overlap an exclusion')


def route_digest(route):
    _validate(route, ROUTE_SCHEMA, 'route')
    return hashlib.sha256(json.dumps(route, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _approval(value, route, task_class):
    _validate(value, APPROVAL_SCHEMA, 'approval')
    if value['config'] != route['config'] or value['task_class'] != task_class or value['route_digest'] != route_digest(route):
        raise RouteError('approval/evaluation metadata does not bind this task class and exact route')
    return value['approved']


def _capability_reason(route, models):
    model = models.get(route['model'])
    if model is None or not model['available']:
        return 'model capability unavailable'
    if route['effort'] not in model['efforts']:
        return 'effort unsupported by model'
    if route['service_tier'] not in model['service_tiers']:
        return 'service tier unsupported by model'
    return None


def resolve_route(contract, capabilities, policy):
    validate_contract(contract)
    _closed(capabilities, ['models'])
    if not isinstance(capabilities['models'], dict):
        raise RouteError('models must be a capability map')
    for identifier, capability in capabilities['models'].items():
        _validate(identifier, ID, 'model id')
        _validate(capability, CAPABILITY_SCHEMA, 'capability')
    _closed(policy, ['incumbent', 'routes'], ['reviewer_route'])
    _validate(policy['incumbent'], ROUTE_SCHEMA, 'incumbent')
    if not isinstance(policy['routes'], dict):
        raise RouteError('routes must be a task-class map')
    for task_class, candidate in policy['routes'].items():
        _validate(task_class, ID, 'task class')
        _closed(candidate, ['route'], ['promotion'])
        _validate(candidate['route'], ROUTE_SCHEMA, 'candidate route')
        if 'promotion' in candidate:
            _approval(candidate['promotion'], candidate['route'], task_class)
    reviewer = policy.get('reviewer_route')
    if reviewer is not None:
        _closed(reviewer, ['route', 'approval'])
        _validate(reviewer['route'], ROUTE_SCHEMA, 'reviewer route')
        _approval(reviewer['approval'], reviewer['route'], 'review')
    task_class = contract['task_class']
    if contract.get('canonical_review_role', False):
        if task_class != 'review' or reviewer is None or not reviewer['approval']['approved']:
            return {'status': 'unsupported', 'reason': 'canonical review requires an explicit approved reviewer route'}
        chosen = reviewer['route']
        reason = _capability_reason(chosen, capabilities['models'])
        return ({'status': 'unsupported', 'reason': reason} if reason else
                {'status': 'resolved', **chosen, 'task_class': task_class, 'policy_basis': 'declared_reviewer_approval'})
    incumbent = policy['incumbent']
    reason = _capability_reason(incumbent, capabilities['models'])
    if reason:
        return {'status': 'unsupported', 'reason': 'incumbent: ' + reason}
    candidate = policy['routes'].get(task_class)
    if candidate and candidate.get('promotion', {}).get('approved') is True:
        reason = _capability_reason(candidate['route'], capabilities['models'])
        if reason is None:
            return {'status': 'resolved', **candidate['route'], 'task_class': task_class, 'policy_basis': 'declared_promotion'}
    else:
        reason = 'task class has no approved promotion'
    return {'status': 'fallback', **incumbent, 'task_class': task_class, 'reason': reason}


def main():
    try:
        payload = json.load(sys.stdin)
        _closed(payload, ['contract', 'capabilities', 'policy'])
        result = resolve_route(**payload)
        print(json.dumps(result))
        return 2 if result['status'] == 'unsupported' else 0
    except (RouteError, ValueError, TypeError) as error:
        print(json.dumps({'status': 'unsupported', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
