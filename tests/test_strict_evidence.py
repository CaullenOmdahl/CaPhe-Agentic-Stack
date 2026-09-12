import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

MODULE_PATH = Path(__file__).parents[1] / 'strict-mode' / 'bin' / 'strict_evidence.py'
SPEC = importlib.util.spec_from_file_location('strict_evidence', MODULE_PATH)
strict_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(strict_evidence)


def record(identifier='change-001', **updates):
    result = {
        'schema_version': 2, 'id': identifier, 'change_id': 'change-001', 'decision': 'ADR-0004',
        'lane': 'scoped-behavior',
        'source': {'repository': 'example/project', 'revision': 'a' * 40, 'snapshot_digest': 'c' * 64},
        'states': {phase: {'status': 'pending', 'scope': 'source'} for phase in
                   ('implementation', 'validation', 'review', 'merge', 'release', 'external_acceptance')},
        'summary': 'Focused checks outstanding',
        'evidence': [{'kind': 'file', 'reference': 'tests/test_example.py'}], 'supersedes': [],
    }
    result.update(updates)
    return result


class StrictEvidenceTests(unittest.TestCase):
    def test_v2_write_immutable_idempotent_and_generated_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            expected = record()
            path = strict_evidence.write_record(root, expected)
            before = path.stat().st_mtime_ns
            strict_evidence.write_record(root, expected)
            self.assertEqual(before, path.stat().st_mtime_ns)
            with self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.write_record(root, record(summary='changed'))
            self.assertEqual(json.loads(path.read_text()), expected)
            index = strict_evidence.generate_index(root).read_text()
            self.assertIn('change-001', index)
            self.assertIn('validation', index)

    def test_conflicting_concurrent_writers_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            def attempt(summary):
                try:
                    strict_evidence.write_record(root, record(summary=summary))
                    return summary
                except strict_evidence.EvidenceError:
                    return None
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(attempt, [f'claim-{i}' for i in range(8)]))
            self.assertEqual(len([x for x in results if x]), 1)
            saved = json.loads((root / '.agent/evidence/change-001.json').read_text())
            self.assertIn(saved['summary'], results)

    def test_rejects_unknown_nested_private_and_unsafe_content(self):
        cases = [record(authorization={'approved': True}), record(summary='token=' + 'sk-' + 'abcdefghijklmno123456789'),
                 record(summary='Read /' + 'Users/example/private/file'), record(id='..')]
        cases.append(record(source={**record()['source'], 'private_path': '/tmp/secret'}))
        cases.append(record(evidence=[{'kind': 'file', 'reference': '../../private'}]))
        cases.append(record(evidence=[{'kind': 'url', 'reference': 'http://127.0.0.1/private'}]))
        cases.append(record(evidence=[{'kind': 'file', 'reference': 'tests/a.py', 'extra': 'hidden'}]))
        for item in cases:
            with self.subTest(item=item), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(item)

    def test_public_https_review_urls_are_valid_and_private_paths_remain_rejected(self):
        for url in ('https://github.com/example/project/pull/7', 'https://example.org/checks/123'):
            with self.subTest(url=url):
                strict_evidence.validate_record(record(evidence=[{'kind': 'url', 'reference': url}]))
        for url in ('https://localhost./checks', 'https://127.1/checks', 'https://127.0.0.1/checks'):
            with self.subTest(url=url), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(record(evidence=[{'kind': 'url', 'reference': url}]))
        for summary in ('Read C:/sensitive/state', 'Read C:' + chr(92) + 'sensitive' + chr(92) + 'state'):
            with self.subTest(summary=summary), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(record(summary=summary))

    def test_absolute_paths_in_prose_and_criteria_are_rejected_before_public_write(self):
        paths = ('/root/customer/project', '/workspace/private-client/result',
                 '/container-client/result', '//mounted-client/result',
                 '/var/customer/result', '%2Fworkspace%2Fclient%2Fresult',
                 '%252Froot%252Fcustomer%252Fsecret',
                 '%25252Fworkspace%25252Fcustomer%25252Fresult',
                 r'\\server\share\user\result.json', quote(r'\\server\share\user\result.json', safe=''))
        for path in paths:
            for field in ('summary', 'reason', 'criterion'):
                with self.subTest(path=path, field=field), tempfile.TemporaryDirectory() as tmp:
                    item = record()
                    text = 'Observed output at `' + path + '`'
                    if field == 'summary':
                        item['summary'] = text
                    elif field == 'reason':
                        item['states']['validation']['reason'] = text
                    else:
                        item['artifact'] = {'sha256': 'b' * 64, 'reference': 'artifacts/render.png'}
                        item['semantic_acceptance'] = {
                            'schema_version': 1, 'source': item['source'], 'artifact': item['artifact'],
                            'display_contract': {'intended': 'Label fits', 'criteria': [text]},
                            'scope': {'kind': 'visual', 'viewport': {'width': 1280, 'height': 720}},
                            'observations': [{'kind': 'file', 'reference': 'artifacts/render.png'}],
                        }
                    root = Path(tmp).resolve()
                    with self.assertRaises(strict_evidence.EvidenceError):
                        strict_evidence.write_record(root, item)
                    self.assertFalse((root / '.agent').exists())

    def test_unc_paths_are_rejected_by_legacy_write_validation(self):
        for value in (r'\\server\share\user\result.json', quote(r'\\server\share\user\result.json', safe='')):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                legacy = {'id': 'legacy', 'decision': 'ADR-0001', 'lane': 'scoped-behavior',
                          'status': 'verified', 'tests': ['python3 -m unittest'], 'review': value}
                with self.assertRaises(strict_evidence.EvidenceError):
                    strict_evidence.write_record(root, legacy)
                self.assertFalse((root / '.agent').exists())

    def test_relative_paths_and_public_https_urls_remain_valid_in_prose(self):
        for summary in ('Read docs/plan.md and tests/test_example.py', 'Read docs/(public)/result.md',
                        'Compare pass/fail and 1/2 acceptance',
                        r'Regex \\d+ matched docs/plan.md',
                        'Review https://github.com/example/project/pull/7',
                        'See https://example.org/reports/(public)/result'):
            with self.subTest(summary=summary):
                strict_evidence.validate_record(record(summary=summary))

    def test_absolute_path_delimiters_and_unsafe_url_spans_are_not_exempt(self):
        for summary in ('path=/opt/client', 'Output:/custom-client/result', '(/srv/client)',
                        '///mounted-client/result', 'See https://localhost/client/result',
                        'See https://[malformed/client/result',
                        'See [report](https://example.org/checks)(/root/customer/project)',
                        "See 'https://example.org/checks',/workspace/private-client/result"):
            with self.subTest(summary=summary), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(record(summary=summary))

    def test_encoded_file_credentials_cannot_enter_evidence_or_artifact_references(self):
        reference = 'tests/%61pi_key%3Dsk%2D' + 'a' * 20
        cases = [record(evidence=[{'kind': 'file', 'reference': reference}]),
                 record(artifact={'sha256': 'e' * 64, 'reference': reference})]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(item)

    def test_loose_legacy_history_is_readable_but_not_promoted_or_rewritten(self):
        legacy = {'id': 'legacy', 'decision': 'ADR-0001', 'lane': 'scoped-behavior',
                  'status': 'verified', 'tests': ['python3 -m unittest'], 'review': 'old review',
                  'private_unknown': 'legacy annotation'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            directory = root / '.agent/evidence'
            directory.mkdir(parents=True)
            (directory / 'legacy.json').write_text(json.dumps(legacy))
            index = strict_evidence.generate_index(root).read_text()
            self.assertIn('legacy', index)
            self.assertIn('unbound', index)
            self.assertNotIn('private_unknown', index)
            with self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.write_record(root, legacy)

    def test_legacy_python_api_preserves_immutable_unbound_notes(self):
        for version in ({}, {'schema_version': 1}):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                legacy = {'id': 'legacy', 'decision': 'ADR-0001', 'lane': 'scoped-behavior',
                          'status': 'verified', 'tests': ['python3 -m unittest'],
                          'review': 'https://example.invalid/pr/1', **version}
                path = strict_evidence.write_record(root, legacy)
                self.assertEqual(json.loads(path.read_text()), legacy)
                modified = path.stat().st_mtime_ns
                self.assertEqual(strict_evidence.write_record(root, legacy), path)
                self.assertEqual(path.stat().st_mtime_ns, modified)
                with self.assertRaises(strict_evidence.EvidenceError):
                    strict_evidence.write_record(root, {**legacy, 'status': 'changed'})
                index = strict_evidence.generate_index(root).read_text()
                self.assertIn('ADR-0001', index)
                self.assertIn('unbound', index)
                for value in ('verified', 'python3 -m unittest', 'https://example.invalid/pr/1'):
                    self.assertNotIn(value, index)
                view = strict_evidence.build_active_view([legacy], record()['source'])
                self.assertTrue(view[0]['legacy_unbound'])
                self.assertTrue(view[0]['stale_source'])
                with self.assertRaises(strict_evidence.EvidenceError):
                    strict_evidence.write_record(root, record(supersedes=['legacy']))

    def test_legacy_compatibility_writes_are_closed_bounded_and_public(self):
        legacy = {'id': 'legacy', 'decision': 'ADR-0001', 'lane': 'scoped-behavior',
                  'status': 'verified', 'tests': ['python3 -m unittest'],
                  'review': 'https://example.invalid/pr/1'}
        changes = [{'private_unknown': 'annotation'}, {'source': record()['source']},
                   {'states': record()['states']}, {'supersedes': []},
                   {'schema_version': None}, {'schema_version': True}, {'schema_version': 1.0},
                   {'tests': ['x' * 1001]}, {'tests': ['test'] * 81},
                   {'tests': ['Read /' + 'home/client/.env']}, {'review': 'api_key=private-fixture'},
                   {'decision': 'ADR-0001 | private annotation'}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with self.assertRaises(strict_evidence.EvidenceError):
                    strict_evidence.write_record(root, {**legacy, **change})
                self.assertFalse((root / '.agent').exists())

    def test_cli_remains_v2_only_for_valid_legacy_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / 'legacy.json'
            source.write_text(json.dumps({'id': 'legacy', 'decision': 'ADR-0001',
                'lane': 'scoped-behavior', 'status': 'verified', 'tests': ['python3 -m unittest'],
                'review': 'https://example.invalid/pr/1'}))
            result = subprocess.run([sys.executable, str(MODULE_PATH), str(source), '--root', str(root)],
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn('schema_version 2', result.stderr)
            self.assertFalse((root / '.agent').exists())

    def test_active_view_excludes_superseded_and_terminal_and_marks_stale(self):
        first = record('first')
        second = record('second', supersedes=['first'])
        terminal = record('terminal', change_id='done', states={
            phase: ({'status': 'passed', 'scope': 'source'} if phase in ('implementation', 'validation', 'review')
                    else {'status': 'not_applicable', 'scope': 'source', 'reason': 'Not requested'})
            for phase in record()['states']})
        source = {**record()['source'], 'revision': 'b' * 40}
        view = strict_evidence.build_active_view([first, second, terminal], source)
        self.assertEqual([item['id'] for item in view], ['second'])
        self.assertTrue(view[0]['stale_source'])
        self.assertEqual(first['supersedes'], [])

    def test_implementation_success_does_not_hide_outstanding_acceptance(self):
        item = record()
        item['states']['implementation']['status'] = 'passed'
        view = strict_evidence.build_active_view([item], item['source'])
        self.assertEqual(len(view), 1)
        self.assertFalse(view[0]['stale_source'])
        changed = {**item['source'], 'snapshot_digest': 'd' * 64}
        self.assertTrue(strict_evidence.build_active_view([item], changed)[0]['stale_source'])
        del item['states']['external_acceptance']
        with self.assertRaises(strict_evidence.EvidenceError):
            strict_evidence.validate_record(item)

    def test_supersession_rejects_dangling_cycles_cross_scope_and_forks(self):
        groups = [[record('a', supersedes=['missing'])],
                  [record('a', supersedes=['b']), record('b', supersedes=['a'])],
                  [record('a'), record('b', supersedes=['a']), record('c', supersedes=['a'])],
                  [record('a'), record('b', change_id='other', supersedes=['a'])]]
        for group in groups:
            with self.subTest(group=group), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.build_active_view(group, record()['source'])

    def test_artifact_acceptance_requires_artifact_binding_and_na_requires_reason(self):
        item = record()
        item['states']['release'] = {'status': 'passed', 'scope': 'artifact'}
        with self.assertRaises(strict_evidence.EvidenceError):
            strict_evidence.validate_record(item)
        item['artifact'] = {'sha256': 'e' * 64, 'reference': 'artifacts/package.zip'}
        strict_evidence.validate_record(item)
        item['states']['merge'] = {'status': 'not_applicable', 'scope': 'source'}
        with self.assertRaises(strict_evidence.EvidenceError):
            strict_evidence.validate_record(item)
        item['states']['merge']['reason'] = 'Merge was not requested'
        strict_evidence.validate_record(item)

    def test_schema_files_match_runtime_schemas(self):
        root = Path(__file__).parents[1]
        for name, schema in [('public-evidence-v2.json', strict_evidence.PUBLIC_SCHEMA),
                             ('semantic-acceptance-v1.json', strict_evidence.SEMANTIC_SCHEMA)]:
            self.assertEqual(json.loads((root / 'schemas' / name).read_text()), schema)

    def test_writer_rejects_dangling_supersession_before_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.write_record(root, record(supersedes=['missing']))
            self.assertFalse((root / '.agent/evidence/change-001.json').exists())

    def test_symlink_evidence_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / '.agent').mkdir()
            (root / 'elsewhere').mkdir()
            (root / '.agent/evidence').symlink_to(root / 'elsewhere', target_is_directory=True)
            with self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.write_record(root, record())

    def test_semantic_acceptance_binds_contract_and_scope_without_verifying(self):
        acceptance = {
            'schema_version': 1, 'source': record()['source'],
            'artifact': {'sha256': 'b' * 64, 'reference': 'artifacts/render.png'},
            'display_contract': {'intended': 'Label fits the button', 'criteria': ['No clipped label']},
            'scope': {'kind': 'visual', 'viewport': {'width': 1280, 'height': 720}},
            'observations': [{'kind': 'file', 'reference': 'artifacts/render.png'}],
        }
        self.assertIsNone(strict_evidence.validate_semantic_acceptance(acceptance))
        for item in ({**acceptance, 'verified': True}, {**acceptance, 'artifact': {'reference': 'x'}},
                     {**acceptance, 'scope': {'kind': 'hardware'}}):
            with self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_semantic_acceptance(item)

    def test_nested_encoded_references_reject_traversal_private_paths_and_credentials(self):
        for raw in ('../outside/result.md', 'docs/private/result.md', 'docs/.env',
                    '/root/customer/secret', 'tests/api_key=sk-' + 'a' * 20):
            encoded = quote(quote(raw, safe=''), safe='')
            for field in ('evidence', 'artifact'):
                with self.subTest(raw=raw, field=field), tempfile.TemporaryDirectory() as tmp:
                    item = record()
                    if field == 'evidence': item['evidence'] = [{'kind': 'file', 'reference': encoded}]
                    else: item['artifact'] = {'sha256': 'e' * 64, 'reference': encoded}
                    root = Path(tmp).resolve()
                    with self.assertRaises(strict_evidence.EvidenceError): strict_evidence.write_record(root, item)
                    self.assertFalse((root / '.agent').exists())
        for raw in ('https://user@example.org/result', 'https://localhost/result', 'https://example.org/result?secret=value'):
            encoded = raw.replace('@', '%2540').replace('localhost', '%256cocalhost').replace('?', '%253F').replace('=', '%253D')
            with self.subTest(url=encoded), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(record(evidence=[{'kind': 'url', 'reference': encoded}]))

    def test_nested_encoding_retains_valid_urls_relative_paths_and_percent_prose(self):
        for summary in ('Progress 100%; literal %zz and %.', 'Progress 100%2525 complete',
                        'Read docs%252Fplan.md', 'See https://example.org/reports/%2528public%2529/result'):
            item = record(summary=summary); before = copy.deepcopy(item)
            strict_evidence.validate_record(item)
            self.assertEqual(item, before)
        for kind, reference in (('file', 'docs%252Fplan.md'), ('file', 'docs/100%2525-complete.md'),
                                ('url', 'https://example.org/reports/%2528public%2529/result')):
            strict_evidence.validate_record(record(evidence=[{'kind': kind, 'reference': reference}]))

    def test_encoding_depth_is_bounded_and_nested_secrets_and_controls_reject(self):
        permitted = 'docs/result.md'
        for _ in range(8): permitted = quote(permitted, safe='')
        strict_evidence.validate_record(record(summary=permitted, evidence=[{'kind': 'file', 'reference': permitted}]))
        excessive = quote(permitted, safe='')
        for item in (record(summary=excessive), record(evidence=[{'kind': 'file', 'reference': excessive}])):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with self.assertRaisesRegex(strict_evidence.EvidenceError, 'depth limit'): strict_evidence.write_record(root, item)
                self.assertFalse((root / '.agent').exists())
        for raw in ('api_key=sk-' + 'a' * 20, 'line\nbreak'):
            encoded = raw
            for _ in range(3): encoded = quote(encoded, safe='')
            with self.subTest(raw=raw), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(record(summary=encoded))

    def test_duplicate_evidence_keys_reject_index_generation_without_replacing_index(self):
        canonical = json.dumps(record())
        cases = {
            'id': canonical.replace('"id": "change-001"', '"id": "other-id", "id": "change-001"'),
            'nested-status': canonical.replace('"validation": {"status": "pending"', '"validation": {"status": "failed", "status": "passed"', 1),
            'identical-id': canonical.replace('"id": "change-001"', '"id": "change-001", "id": "change-001"'),
        }
        for kind, content in cases.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); directory = root / '.agent/evidence'; directory.mkdir(parents=True)
                path = directory / 'change-001.json'; path.write_text(content)
                index = root / '.agent/traceability.md'; index.write_text('Prior index must survive.\n')
                with self.assertRaises(strict_evidence.EvidenceError): strict_evidence.generate_index(root)
                self.assertEqual(path.read_text(), content)
                self.assertEqual(index.read_text(), 'Prior index must survive.\n')

    def test_duplicate_existing_record_cannot_be_adopted_as_idempotent_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); item = record()
            path = strict_evidence.write_record(root, item)
            content = json.dumps(item).replace('"id": "change-001"', '"id": "other-id", "id": "change-001"')
            path.write_text(content)
            with self.assertRaisesRegex(strict_evidence.EvidenceError, 'duplicate keys'):
                strict_evidence.write_record(root, item)
            self.assertEqual(path.read_text(), content)

    def test_cli_record_and_active_source_files_reject_duplicate_keys(self):
        for kind in ('record', 'active-source'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp).resolve(); root = base / 'repo'; root.mkdir()
                incoming = base / 'incoming.json'
                if kind == 'record':
                    content = json.dumps(record()).replace('"id": "change-001"', '"id": "other-id", "id": "change-001"')
                    arguments = [str(incoming)]
                else:
                    content = json.dumps(record()['source']).replace('"repository": "example/project"', '"repository": "other/project", "repository": "example/project"')
                    arguments = ['--active-source', str(incoming)]
                incoming.write_text(content)
                result = subprocess.run([sys.executable, str(MODULE_PATH), '--root', str(root), *arguments],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('duplicate keys', result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertFalse((root / '.agent/traceability.md').exists())
                self.assertEqual(list(root.rglob('*.json')), [])
                self.assertEqual(incoming.read_text(), content)


if __name__ == '__main__':
    unittest.main()
