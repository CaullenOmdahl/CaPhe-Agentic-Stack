#!/usr/bin/env python3
"""Immutable public evidence snapshots; declarations never certify their own claims."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import fcntl
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from urllib.parse import urlsplit, unquote


class EvidenceError(ValueError):
    pass


PHASES = ('implementation', 'validation', 'review', 'merge', 'release', 'external_acceptance')
ID_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
REPOSITORY_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'
SHA256 = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 1000}


def _object(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


SOURCE_SCHEMA = _object({
    'repository': {'type': 'string', 'pattern': REPOSITORY_PATTERN},
    'revision': {'type': 'string', 'pattern': r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$'},
    'snapshot_digest': SHA256,
})
ARTIFACT_SCHEMA = _object({'sha256': SHA256, 'reference': TEXT})
REFERENCE_SCHEMA = _object({'kind': {'enum': ['file', 'url', 'digest', 'check']}, 'reference': TEXT})
STATE_SCHEMA = _object({
    'status': {'enum': ['pending', 'passed', 'failed', 'blocked', 'not_applicable']},
    'scope': {'enum': ['source', 'artifact', 'device']},
    'reason': TEXT,
}, ['status', 'scope'])
STATE_SCHEMA['allOf'] = [{'if': {'properties': {'status': {'const': 'not_applicable'}}},
                           'then': {'required': ['reason']}}]
SEMANTIC_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'Semantic acceptance declaration, not verification',
    **_object({
        'schema_version': {'const': 1}, 'source': SOURCE_SCHEMA, 'artifact': ARTIFACT_SCHEMA,
        'display_contract': _object({'intended': TEXT, 'criteria': {
            'type': 'array', 'minItems': 1, 'maxItems': 40, 'items': TEXT}}),
        'scope': _object({
            'kind': {'enum': ['visual', 'hardware']},
            'viewport': _object({'width': {'type': 'integer', 'minimum': 1, 'maximum': 32768},
                                 'height': {'type': 'integer', 'minimum': 1, 'maximum': 32768}}),
            'device': _object({'family': TEXT, 'identifier': {'type': 'string', 'pattern': ID_PATTERN}}),
        }, ['kind']),
        'observations': {'type': 'array', 'minItems': 1, 'maxItems': 40, 'items': REFERENCE_SCHEMA},
    }),
}
SEMANTIC_SCHEMA['properties']['scope']['allOf'] = [
    {'if': {'properties': {'kind': {'const': kind}}}, 'then': {'required': [field]}}
    for kind, field in [('visual', 'viewport'), ('hardware', 'device')]
]
PUBLIC_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'Public evidence snapshot v2',
    **_object({
        'schema_version': {'const': 2},
        'id': {'type': 'string', 'pattern': ID_PATTERN},
        'change_id': {'type': 'string', 'pattern': ID_PATTERN},
        'decision': {'type': 'string', 'pattern': r'^ADR-[0-9]{4,}$'},
        'lane': {'enum': ['mechanically-proven', 'scoped-behavior', 'full-risk']},
        'source': SOURCE_SCHEMA, 'artifact': ARTIFACT_SCHEMA,
        'states': _object({phase: STATE_SCHEMA for phase in PHASES}),
        'summary': TEXT,
        'evidence': {'type': 'array', 'minItems': 1, 'maxItems': 80, 'items': REFERENCE_SCHEMA},
        'supersedes': {'type': 'array', 'maxItems': 1, 'uniqueItems': True,
                       'items': {'type': 'string', 'pattern': ID_PATTERN}},
        'semantic_acceptance': SEMANTIC_SCHEMA,
    }, ['schema_version', 'id', 'change_id', 'decision', 'lane', 'source', 'states',
        'summary', 'evidence', 'supersedes']),
}


# Conditional bindings are present in both the distributed schema and the stdlib validator.
PUBLIC_SCHEMA['allOf'] = []
for _phase in PHASES:
    for _scope in ('artifact', 'device'):
        PUBLIC_SCHEMA['allOf'].append({
            'if': {'properties': {'states': {'properties': {_phase: {'properties': {'scope': {'const': _scope}}}}}}},
            'then': {'required': ['artifact']},
        })
    PUBLIC_SCHEMA['allOf'].append({
        'if': {'properties': {'states': {'properties': {_phase: {'properties': {'scope': {'const': 'device'}}}}}}},
        'then': {'required': ['semantic_acceptance'], 'properties': {
            'semantic_acceptance': {'properties': {'scope': {'properties': {'kind': {'const': 'hardware'}}}}}}},
    })
for _phase in ('release', 'external_acceptance'):
    PUBLIC_SCHEMA['allOf'].append({
        'if': {'properties': {'states': {'properties': {_phase: {'properties': {'status': {'const': 'passed'}}}}}}},
        'then': {'properties': {'states': {'properties': {_phase: {'properties': {'scope': {'enum': ['artifact', 'device']}}}}}}},
    })


def _validate(value, schema, location='record'):
    """Validate the deliberately small JSON Schema vocabulary used above."""
    for condition in schema.get('allOf', []):
        _validate(value, condition, location)
    if 'if' in schema:
        try:
            _validate(value, schema['if'], location)
        except EvidenceError:
            _validate(value, schema.get('else', {}), location)
        else:
            _validate(value, schema.get('then', {}), location)
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise EvidenceError(f'{location}: invalid constant')
    if 'enum' in schema and value not in schema['enum']:
        raise EvidenceError(f'{location}: unsupported value')
    kind = schema.get('type')
    if kind == 'object' or 'properties' in schema or 'required' in schema:
        if not isinstance(value, dict):
            raise EvidenceError(f'{location}: expected object')
        if schema.get('additionalProperties') is False and set(value) - set(schema['properties']):
            raise EvidenceError(f'{location}: unknown fields are not public evidence')
        if set(schema.get('required', [])) - set(value):
            raise EvidenceError(f'{location}: missing required fields')
        for key, item in value.items():
            if key in schema.get('properties', {}):
                _validate(item, schema['properties'][key], f'{location}.{key}')
    elif kind == 'array':
        if not isinstance(value, list) or not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 100):
            raise EvidenceError(f'{location}: invalid array')
        if schema.get('uniqueItems') and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            raise EvidenceError(f'{location}: duplicates are not allowed')
        for item in value:
            _validate(item, schema['items'], location + '[]')
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 1000):
            raise EvidenceError(f'{location}: invalid string')
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
            raise EvidenceError(f'{location}: invalid format')
    elif kind == 'integer':
        if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
            raise EvidenceError(f'{location}: invalid integer')


def _validate_public_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').rstrip('.')
    except ValueError as error:
        raise EvidenceError('invalid evidence URL') from error
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise EvidenceError('evidence URL must be public HTTPS without credentials/query/fragment')
    if '.' not in host or host.endswith(('.local', '.internal', '.localhost')) or host == 'localhost':
        raise EvidenceError('private host reference rejected')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    numeric_host = re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*', host)
    if address is not None or numeric_host:
        raise EvidenceError('IP-address evidence URLs are not public references')


def _remove_public_url_scheme(match):
    try:
        _validate_public_url(match.group())
    except EvidenceError:
        return match.group()
    return match.group()[len('https://'):]


def _public_text(value):
    """Conservative leak guard, not a guarantee that arbitrary prose is sanitized."""
    if isinstance(value, dict):
        for item in value.values():
            _public_text(item)
    elif isinstance(value, list):
        for item in value:
            _public_text(item)
    elif isinstance(value, str):
        patterns = (
            r'/(?:Users|home|private|tmp|etc)/', r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]', r'~/',
            r'(?:sk-|gh[pousr]_|github_' r'pat_)[A-Za-z0-9_-]{16,}',
            r'BEGIN [A-Z ]*PRIVATE KEY', r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}',
            r'(?i)\b(?:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+',
            r'\b(?:127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b',
        )
        decoded = unquote(value)
        if any(re.search(pattern, text) for pattern in patterns for text in (value, decoded)) or any(ord(c) < 32 for c in decoded):
            raise EvidenceError('public evidence contains unsafe/private-looking content')
        # Exempt only a validated HTTPS scheme delimiter. Keep the rest visible so
        # quoted/Markdown URLs cannot hide an adjoining local path from the guard.
        prose = re.sub(r'https://[^\s<>"`]+', _remove_public_url_scheme, decoded)
        if re.search(r'''(?:^|[\s'"`([{=:,;<>])/+(?=[^\s/])''', prose):
            raise EvidenceError('public evidence contains an absolute local path')


def _reference(item):
    value = item['reference']
    kind = item['kind']
    decoded = unquote(value)
    if kind == 'file':
        _public_text(decoded)
        path = PurePosixPath(decoded)
        if (path.is_absolute() or '\\' in decoded or ':' in decoded or
                any(part in ('', '.', '..') for part in decoded.split('/')) or
                any(part in ('.git', '.codex', '.ssh', 'private') or part.startswith('.env') for part in path.parts)):
            raise EvidenceError('evidence file reference must be a sanitized relative path')
    elif kind == 'url':
        _validate_public_url(value)
        _public_text(decoded)
    elif kind == 'digest' and re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise EvidenceError('digest reference must be SHA-256')
    elif kind == 'check' and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 .:_/-]{0,200}', value) is None:
        raise EvidenceError('check reference must be a label, not raw command output')


def _artifact(artifact):
    _reference({'kind': 'file', 'reference': artifact['reference']})


def validate_semantic_acceptance(record):
    _validate(record, SEMANTIC_SCHEMA)
    _public_text(record)
    _artifact(record['artifact'])
    scope = record['scope']
    if scope['kind'] == 'visual' and 'viewport' not in scope:
        raise EvidenceError('visual declaration requires viewport scope')
    if scope['kind'] == 'hardware' and 'device' not in scope:
        raise EvidenceError('hardware declaration requires device scope')
    for item in record['observations']:
        _reference(item)


def validate_record(record: dict[str, Any]) -> None:
    if not isinstance(record, dict) or record.get('schema_version') != 2:
        raise EvidenceError('new writes require public evidence schema_version 2; legacy records are read-only and unbound')
    _validate(record, PUBLIC_SCHEMA)
    _public_text(record)
    for item in record['evidence']:
        _reference(item)
    if 'artifact' in record:
        _artifact(record['artifact'])
    for phase, state in record['states'].items():
        if state['status'] == 'not_applicable' and not state.get('reason'):
            raise EvidenceError('not_applicable requires an explicit scope reason')
        if state['scope'] in ('artifact', 'device') and 'artifact' not in record:
            raise EvidenceError('artifact/device scope requires artifact binding')
        if phase in ('release', 'external_acceptance') and state['status'] == 'passed' and state['scope'] == 'source':
            raise EvidenceError('release/external acceptance success requires artifact or device scope')
    if 'semantic_acceptance' in record:
        semantic = record['semantic_acceptance']
        validate_semantic_acceptance(semantic)
        if semantic['source'] != record['source'] or semantic['artifact'] != record.get('artifact'):
            raise EvidenceError('semantic declaration must match snapshot source and artifact')
    if any(state['scope'] == 'device' for state in record['states'].values()):
        if record.get('semantic_acceptance', {}).get('scope', {}).get('kind') != 'hardware':
            raise EvidenceError('device scope requires a hardware acceptance declaration')


def _validate_legacy(record):
    fields = ('id', 'decision', 'lane', 'status', 'tests', 'review')
    if not isinstance(record, dict) or any(field not in record for field in fields):
        raise EvidenceError('invalid legacy evidence')
    if record.get('schema_version') not in (None, 1):
        raise EvidenceError('unsupported evidence version')
    if not isinstance(record['id'], str) or re.fullmatch(ID_PATTERN, record['id']) is None:
        raise EvidenceError('invalid legacy evidence id')
    if any(not isinstance(record[key], str) for key in ('decision', 'lane', 'status', 'review')):
        raise EvidenceError('invalid legacy evidence fields')
    if not isinstance(record['tests'], list) or any(not isinstance(item, str) for item in record['tests']):
        raise EvidenceError('invalid legacy test list')


def _validate_history(records):
    by_id = {}
    successors = {}
    for record in records:
        if not isinstance(record, dict):
            raise EvidenceError('evidence history must contain objects')
        (validate_record if record.get('schema_version') == 2 else _validate_legacy)(record)
        if record['id'] in by_id:
            raise EvidenceError('duplicate evidence id')
        by_id[record['id']] = record
    for record in records:
        if record.get('schema_version') != 2:
            continue
        for prior in record['supersedes']:
            if prior not in by_id:
                raise EvidenceError('dangling supersession reference')
            old = by_id[prior]
            if old.get('schema_version') != 2 or old['change_id'] != record['change_id'] or old['source']['repository'] != record['source']['repository']:
                raise EvidenceError('supersession cannot cross change/repository scope or promote legacy evidence')
            if prior in successors:
                raise EvidenceError('ambiguous supersession successors')
            successors[prior] = record['id']
    for identifier in by_id:
        visited = set()
        cursor = identifier
        while cursor in successors:
            if cursor in visited:
                raise EvidenceError('cyclic supersession')
            visited.add(cursor)
            cursor = successors[cursor]
    heads = set()
    for identifier, item in by_id.items():
        if item.get('schema_version') == 2 and identifier not in successors:
            scope = (item['source']['repository'], item['change_id'])
            if scope in heads:
                raise EvidenceError('ambiguous current snapshots; explicitly supersede the prior snapshot')
            heads.add(scope)
    return successors


def build_active_view(records, current_source):
    _validate(current_source, SOURCE_SCHEMA, 'current_source')
    successors = _validate_history(records)
    active = []
    for record in sorted(records, key=lambda item: item['id']):
        if record['id'] in successors:
            continue
        if record.get('schema_version') != 2:
            active.append({'id': record['id'], 'legacy_unbound': True, 'stale_source': True})
        elif not all(state['status'] in ('passed', 'not_applicable') for state in record['states'].values()):
            active.append({**copy.deepcopy(record), 'stale_source': record['source'] != current_source})
    return active


def _no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise EvidenceError('symlink paths are not accepted for evidence storage')


def _directory(root):
    root = Path(root).absolute()
    _no_symlinks(root)
    directory = root / '.agent' / 'evidence'
    _no_symlinks(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@contextmanager
def _locked(directory):
    path = directory / '.write.lock'
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _no_symlinks(directory)
        yield
    finally:
        os.close(descriptor)


def _canonical(record):
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n'


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise EvidenceError('evidence records must be regular files')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as error:
        raise EvidenceError('cannot read valid evidence JSON') from error


def _records(directory):
    result = []
    for path in sorted(directory.glob('*.json')):
        item = _read(path)
        if not isinstance(item, dict) or item.get('id') != path.stem:
            raise EvidenceError('record id must match its filename')
        result.append(item)
    return result


def _atomic_write(path, content, immutable=False):
    _no_symlinks(path)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    tmp = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if immutable:
            try:
                os.link(tmp, path)
            except FileExistsError as error:
                raise EvidenceError('conflicting evidence id cannot overwrite history') from error
        else:
            os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def write_record(root: Path, record: dict[str, Any]) -> Path:
    validate_record(record)
    directory = _directory(root)
    path = directory / (record['id'] + '.json')
    with _locked(directory):
        if path.exists() or path.is_symlink():
            if _canonical(_read(path)) == _canonical(record):
                return path
            raise EvidenceError('conflicting evidence id cannot overwrite history; use a new id and supersedes')
        records = _records(directory)
        _validate_history([*records, record])
        _atomic_write(path, _canonical(record), immutable=True)
    return path


def _cell(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ')


def generate_index(root: Path) -> Path:
    directory = _directory(root)
    with _locked(directory):
        records = _records(directory)
        successors = _validate_history(records)
        lines = ['# Traceability', '',
                 '> Generated from `.agent/evidence/*.json`. Claims are not independent verification.', '',
                 '| Record | Decision | Lane | Acceptance states | Binding |', '|---|---|---|---|---|']
        for record in records:
            if record.get('schema_version') == 2:
                status = '; '.join(f'{phase}: {state["status"]}' for phase, state in record['states'].items())
                binding = record['source']['revision'][:12] + '/' + record['source']['snapshot_digest'][:12]
                if record['id'] in successors:
                    binding += ' superseded by ' + successors[record['id']]
                cells = [record['id'], record['decision'], record['lane'], status, binding]
            else:
                cells = [record['id'], 'legacy', 'unbound', 'unknown acceptance', 'legacy; provenance not promoted']
            lines.append('| ' + ' | '.join(_cell(cell) for cell in cells) + ' |')
        path = directory.parent / 'traceability.md'
        _atomic_write(path, '\n'.join(lines) + '\n')
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', nargs='?', help='public v2 JSON snapshot (legacy writes are rejected)')
    parser.add_argument('--root', default='.')
    parser.add_argument('--index-only', action='store_true')
    parser.add_argument('--active-source', help='source JSON; print active snapshots without changing the index')
    args = parser.parse_args()
    try:
        root = Path(args.root).absolute()
        if args.active_source:
            directory = _directory(root)
            with _locked(directory):
                print(json.dumps(build_active_view(_records(directory), _read(Path(args.active_source))), indent=2))
        else:
            if not args.index_only:
                if not args.record:
                    parser.error('record is required unless --index-only is used')
                write_record(root, _read(Path(args.record)))
            generate_index(root)
    except (EvidenceError, OSError) as error:
        parser.exit(2, f'evidence rejected: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
