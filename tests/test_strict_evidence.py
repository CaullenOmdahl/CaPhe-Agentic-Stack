import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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

    def test_encoded_file_credentials_cannot_enter_evidence_or_artifact_references(self):
        reference = 'tests/%61pi_key%3Dsk%2D' + 'a' * 20
        cases = [record(evidence=[{'kind': 'file', 'reference': reference}]),
                 record(artifact={'sha256': 'e' * 64, 'reference': reference})]
        for item in cases:
            with self.subTest(item=item), self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.validate_record(item)

    def test_legacy_is_readable_but_not_promoted_or_writable(self):
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


if __name__ == '__main__':
    unittest.main()
