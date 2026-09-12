import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


MODULE = Path(__file__).parents[1] / 'tools' / 'stack_state.py'


def load_module():
    spec = importlib.util.spec_from_file_location('stack_state', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.module = load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, base=None, repository='example/project'):
        return self.module.PrivateStateStore(base or self.root / 'private', self.repo, repository)

    def test_private_state_roundtrip_owner_only_and_scoped(self):
        store = self.store()
        store.write_task('task-1', {'next_action': 'verify source', 'authorization_id': 'auth-1'})
        self.assertEqual(store.read_task('task-1')['next_action'], 'verify source')
        self.assertIsNone(self.store(repository='example/other').read_task('task-1'))
        for path in (self.root / 'private').rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o077, 0, path)
        self.assertEqual((self.root / 'private').stat().st_mode & 0o077, 0)

    def test_authorization_is_immutable_and_not_exported(self):
        store = self.store()
        auth = {'action': 'publish branch', 'scope': 'example/project', 'user_statement': 'Approved for this task'}
        store.write_authorization('auth-1', auth)
        store.write_authorization('auth-1', auth)
        self.assertEqual(store.read_authorization('auth-1'), auth)
        with self.assertRaises(self.module.StateError):
            store.write_authorization('auth-1', {**auth, 'action': 'merge'})
        self.assertEqual(list(self.repo.rglob('*.json')), [])

    def test_duplicate_envelope_and_nested_authorization_keys_are_rejected(self):
        store = self.store()
        auth = {'action': 'publish branch', 'scope': 'example/project', 'user_statement': 'Approved for this task'}
        for field, values in (('id', ('other-id', 'auth-1')),
                              ('action', ('inspect only', 'publish branch')),
                              ('user_statement', ('Not approved', 'Approved for this task'))):
            for reverse in (False, True):
                with self.subTest(field=field, reverse=reverse):
                    pair = values[::-1] if reverse else values
                    envelope = {'schema_version': 1, 'repository': 'example/project', 'id': 'auth-1', 'data': auth}
                    content = json.dumps(envelope)
                    original = json.dumps(field) + ': ' + json.dumps(envelope.get(field, auth.get(field)))
                    duplicate = ', '.join(json.dumps(field) + ': ' + json.dumps(value) for value in pair)
                    content = content.replace(original, duplicate)
                    path = store.directory / 'authorizations/auth-1.json'
                    path.write_text(content); path.chmod(0o600)
                    before = (path.read_bytes(), path.stat().st_mode)
                    with self.assertRaises(self.module.StateError): store.read_authorization('auth-1')
                    with self.assertRaises(self.module.StateError): store.write_authorization('auth-1', auth)
                    self.assertEqual((path.read_bytes(), path.stat().st_mode), before)

    def test_duplicate_deep_task_keys_are_rejected_without_overwrite(self):
        store = self.store()
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                pairs = '"approved": false, "approved": true' if not reverse else '"approved": true, "approved": false'
                path = store.directory / 'tasks/task-1.json'
                content = '{"schema_version":1,"repository":"example/project","id":"task-1","data":{"continuation":{"authorization":{' + pairs + '}}}}'
                path.write_text(content); path.chmod(0o600)
                with self.assertRaises(self.module.StateError): store.read_task('task-1')
                with self.assertRaises(self.module.StateError): store.write_task('task-1', {'next_action': 'continue'})
                self.assertEqual(path.read_text(), content)

    def test_concurrent_authorization_writers_preserve_one_record(self):
        store = self.store()
        def attempt(index):
            auth = {'action': f'action-{index}', 'scope': 'example/project', 'user_statement': 'Explicit statement'}
            try:
                store.write_authorization('auth-1', auth)
                return auth
            except self.module.StateError:
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, range(6)))
        winners = [item for item in results if item is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(store.read_authorization('auth-1'), winners[0])

    def test_rejects_inside_any_git_worktree(self):
        with self.assertRaises(self.module.StateError):
            self.store(self.repo / 'private')
        other = self.root / 'other'
        other.mkdir()
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        with self.assertRaises(self.module.StateError):
            self.store(other / 'private')

    def test_existing_task_symlink_cannot_escape_store(self):
        store = self.store()
        path = store.write_task('task-1', {'next_action': 'check'})
        outside = self.root / 'outside.json'
        outside.write_text('preserve')
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(self.module.StateError):
            store.write_task('task-1', {'next_action': 'overwrite'})
        with self.assertRaises(self.module.StateError):
            store.read_task('task-1')
        self.assertEqual(outside.read_text(), 'preserve')

    def test_rejects_canonical_memory_directory(self):
        memory = self.root / '.codex' / 'memories'
        memory.mkdir(parents=True, mode=0o700)
        with self.assertRaises(self.module.StateError):
            self.store(memory)
        with self.assertRaises(self.module.StateError):
            self.store(memory / 'derived')

    def test_parent_segments_cannot_enter_canonical_stores(self):
        codex = self.root / '.codex'
        (codex / 'intermediate').mkdir(parents=True, mode=0o700)
        for name in ('memories', 'sessions'):
            with self.subTest(name=name):
                canonical = codex / name
                canonical.mkdir(mode=0o700)
                sentinel = canonical / 'existing.txt'
                sentinel.write_bytes(b'preserve canonical source\r\n')
                with self.assertRaises(self.module.StateError):
                    self.store(codex / 'intermediate' / '..' / name / 'state')
                self.assertEqual(list(canonical.iterdir()), [sentinel])
                self.assertEqual(sentinel.read_bytes(), b'preserve canonical source\r\n')

    def test_safe_parent_segments_share_the_normalized_store(self):
        intermediate = self.root / 'intermediate'
        intermediate.mkdir(mode=0o700)
        store = self.store(intermediate / '..' / 'private')
        store.write_task('task-1', {'next_action': 'verify'})
        self.assertEqual(self.store().read_task('task-1'), {'next_action': 'verify'})

    def test_canonical_store_exclusion_covers_case_insensitive_hosts(self):
        codex = self.root / '.codex'
        codex.mkdir(mode=0o700)
        for name in ('memories', 'sessions'):
            with self.subTest(name=name):
                canonical = codex / name
                canonical.mkdir(mode=0o700)
                with self.assertRaises(self.module.StateError):
                    self.store(self.root / '.CoDeX' / name.upper() / 'private')
                self.assertEqual(list(canonical.iterdir()), [])

    def test_parent_normalization_does_not_hide_a_symlink(self):
        target = self.root / 'target'
        target.mkdir(mode=0o700)
        alias = self.root / 'alias'
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaises(self.module.StateError):
            self.store(alias / '..' / 'private')
        self.assertFalse((self.root / 'private').exists())

    def test_rejects_unsafe_scope_and_ids(self):
        for scope in ('../escape', '/absolute', 'https://private.example/repo', 'a/b/../../c'):
            with self.assertRaises(self.module.StateError):
                self.store(repository=scope)
        store = self.store()
        for key in ('..', '../escape', 'a/b', ''):
            with self.assertRaises(self.module.StateError):
                store.write_task(key, {})
        with self.assertRaises(self.module.StateError):
            store.write_authorization('auth-1', {'scope': 'other/repo', 'action': 'publish', 'user_statement': 'yes'})

    def test_rejects_symlink_and_permissive_base(self):
        target = self.root / 'target'
        target.mkdir(mode=0o700)
        alias = self.root / 'alias'
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaises(self.module.StateError):
            self.store(alias)
        unsafe = self.root / 'unsafe'
        unsafe.mkdir(mode=0o755)
        with self.assertRaises(self.module.StateError):
            self.store(unsafe)

    def test_malformed_other_repository_config_cannot_hide_private_state_boundary(self):
        other = self.root / 'other'
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        nested = other / 'nested'; nested.mkdir()
        config = other / '.git/config'; config.write_text(config.read_text() + '\n[malformed\n')
        before = {str(path.relative_to(other)): (path.read_bytes(), path.stat().st_mode)
                  for path in other.rglob('*') if path.is_file()}
        with self.assertRaises(self.module.StateError):
            self.store(nested / 'private').write_task('task-1', {'private_fixture': 'preserve'})
        self.assertFalse((nested / 'private').exists())
        self.assertEqual({str(path.relative_to(other)): (path.read_bytes(), path.stat().st_mode)
                          for path in other.rglob('*') if path.is_file()}, before)

    def test_unknown_discovery_errors_fail_closed_without_creating_private_state(self):
        for code, stderr in ((128, 'fatal: bad config line 1 in file fixture\n'),
                             (128, 'fatal: detected dubious ownership in repository\n'),
                             (129, 'unexpected Git error\n')):
            with self.subTest(code=code, stderr=stderr):
                result = subprocess.CompletedProcess([], code, stdout='', stderr=stderr)
                with mock.patch.object(self.module.subprocess, 'run', return_value=result) as probe:
                    with self.assertRaises(self.module.StateError): self.store()
                    self.assertEqual(probe.call_args.kwargs['env']['LC_ALL'], 'C')
                self.assertFalse((self.root / 'private').exists())
        with mock.patch.object(self.module.subprocess, 'run', side_effect=OSError('unavailable')):
            with self.assertRaises(self.module.StateError): self.store()
        self.assertFalse((self.root / 'private').exists())
        # The same location is valid once a genuine nonrepository probe succeeds.
        self.store().write_task('task-1', {'next_action': 'ordinary outside-Git state'})


if __name__ == '__main__':
    unittest.main()
