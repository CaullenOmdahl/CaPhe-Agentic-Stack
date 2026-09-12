import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


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


if __name__ == '__main__':
    unittest.main()
