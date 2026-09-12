import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / 'tools' / 'stack_context.py'
SPEC = importlib.util.spec_from_file_location('stack_context', MODULE_PATH)
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, env=context.isolated_git_environment())


def initialize(repo):
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'tests@example.invalid')
    git(repo, 'config', 'user.name', 'Tests')
    (repo / 'tracked').write_text('base\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')


def message(**changes):
    result = {'id': 'm1', 'kind': 'message', 'role': 'user', 'excerpt': 'requested behavior',
              'source': {'id': 's1', 'coordinate': 'line:1', 'digest': 'd' * 64}}
    result.update(changes)
    return result


class ContextContracts(unittest.TestCase):
    def test_repository_environment_drops_all_git_overrides(self):
        keys = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                'GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0',
                'GIT_CONFIG_PARAMETERS', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES')
        env = context.isolated_git_environment({**dict.fromkeys(keys, 'untrusted'), 'KEEP': 'yes'})
        self.assertFalse(set(keys) & set(env))
        self.assertEqual(env['KEEP'], 'yes')
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')

    def test_porcelain_renames_and_unusual_names_are_one_path(self):
        result = context.project_git_status('R  new\nname\0old name\0?? next\0', max_paths=1)
        self.assertEqual(result['paths'], [{'state': 'R ', 'path': 'new\nname', 'original_path': 'old name'}])
        self.assertEqual(result['omitted_count'], 1)
        self.assertTrue(result['truncated'])
        with self.assertRaises(ValueError):
            context.project_git_status('R  new\0')

    def test_failed_snapshots_never_compare_fresh(self):
        failed = {'head': None, 'working_snapshot': None, 'complete': False}
        self.assertTrue(context.mark_snapshot_freshness(failed, failed)['stale'])
        self.assertTrue(context.mark_snapshot_freshness({}, {})['stale'])

    def test_nested_snapshot_binds_staged_blob_mode_and_untracked_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            initialize(repo)
            (repo / 'nested').mkdir()
            (repo / 'nested' / 'new').write_text('untracked')
            (repo / 'tracked').write_text('staged A')
            git(repo, 'add', 'tracked')
            (repo / 'tracked').write_text('same working content')
            first = context.collect_repository_context(repo)
            self.assertFalse(first['identity']['stale'])
            digest = first['identity']['before']['working_snapshot']
            (repo / 'tracked').write_text('staged B')
            git(repo, 'add', 'tracked')
            (repo / 'tracked').write_text('same working content')
            second = context.collect_repository_context(repo)['identity']['before']['working_snapshot']
            self.assertNotEqual(digest, second)
            git(repo, 'update-index', '--chmod=+x', 'tracked')
            third = context.collect_repository_context(repo)['identity']['before']['working_snapshot']
            self.assertNotEqual(second, third)
            (repo / 'nested' / 'new').write_text('different')
            fourth = context.collect_repository_context(repo)['identity']['before']['working_snapshot']
            self.assertNotEqual(third, fourth)

    def test_tracked_bytes_and_modes_are_bound_when_git_normalizes_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            initialize(repo)
            (repo / '.gitattributes').write_text('tracked filter=constant\n')
            git(repo, 'config', 'filter.constant.clean', 'cat >/dev/null; printf normalized')
            git(repo, 'config', 'core.filemode', 'false')
            (repo / 'tracked').write_text('first')
            git(repo, 'add', '.')
            first = context._snapshot_identity(repo)
            diff = git(repo, 'diff', '--binary', '--no-textconv').stdout
            (repo / 'tracked').write_text('second')
            self.assertEqual(git(repo, 'diff', '--binary', '--no-textconv').stdout, diff)
            second = context._snapshot_identity(repo)
            self.assertTrue(first['complete'] and second['complete'])
            self.assertNotEqual(first['working_snapshot'], second['working_snapshot'])
            (repo / 'tracked').chmod(0o755)
            self.assertEqual(git(repo, 'diff', '--binary', '--no-textconv').stdout, diff)
            third = context._snapshot_identity(repo)
            self.assertTrue(third['complete'])
            self.assertNotEqual(second['working_snapshot'], third['working_snapshot'])

    def test_tracked_deletion_and_reappearance_have_explicit_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            initialize(repo)
            path = repo / 'tracked'
            original = context._snapshot_identity(repo)
            content, mode = path.read_bytes(), path.stat().st_mode & 0o777
            path.unlink()
            deleted = context._snapshot_identity(repo)
            self.assertTrue(deleted['complete'])
            self.assertNotEqual(original['working_snapshot'], deleted['working_snapshot'])
            path.write_bytes(content); path.chmod(mode)
            self.assertEqual(context._snapshot_identity(repo), original)

    def test_tracked_file_replaced_by_directory_binds_visible_children_and_directory_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve(); initialize(repo)
            path = repo / 'tracked'; content = path.read_bytes(); mode = path.stat().st_mode & 0o777
            original = context._snapshot_identity(repo)
            path.unlink(); path.mkdir()
            empty = context._snapshot_identity(repo)
            self.assertTrue(empty['complete'])
            self.assertNotEqual(original['working_snapshot'], empty['working_snapshot'])
            path.chmod(0o700)
            restricted = context._snapshot_identity(repo)
            self.assertTrue(restricted['complete'])
            self.assertNotEqual(empty['working_snapshot'], restricted['working_snapshot'])
            child = path / 'new.py'; child.write_text('first')
            first = context._snapshot_identity(repo)
            child.write_text('second')
            second = context._snapshot_identity(repo)
            self.assertTrue(first['complete'] and second['complete'])
            self.assertNotEqual(first['working_snapshot'], second['working_snapshot'])
            (repo / '.git/info/exclude').write_text('tracked/ignored\n')
            ignored = path / 'ignored'; ignored.write_text('local state')
            self.assertEqual(context._snapshot_identity(repo), second)
            child.unlink(); ignored.unlink(); path.rmdir(); path.write_bytes(content); path.chmod(mode)
            self.assertEqual(context._snapshot_identity(repo), original)

    def test_directory_replaced_by_ignored_file_binds_the_tracked_path_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve(); initialize(repo)
            folder = repo / 'folder'; folder.mkdir()
            child = folder / 'tracked.py'; child.write_text('source')
            git(repo, 'add', 'folder/tracked.py')
            child.unlink(); folder.rmdir(); folder.write_text('first')
            (repo / '.git/info/exclude').write_text('folder\n')
            first = context._snapshot_identity(repo)
            folder.write_text('second')
            second = context._snapshot_identity(repo)
            self.assertTrue(first['complete'] and second['complete'])
            self.assertNotEqual(first['working_snapshot'], second['working_snapshot'])

    def test_large_file_hashing_is_streamed_and_symlink_target_is_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            initialize(repo)
            with (repo / 'large').open('wb') as handle:
                for _ in range(24):
                    handle.write(b'x' * (1024 * 1024))
            (repo / 'link').symlink_to('missing-target')
            git(repo, 'add', 'large', 'link')
            tracemalloc.start()
            try:
                result = context.collect_repository_context(repo)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertFalse(result['identity']['stale'])
            self.assertLess(peak, 8 * 1024 * 1024)

    def test_hidden_tracked_changes_and_repeated_hash_failures_are_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            initialize(repo)
            for flag in ('--assume-unchanged', '--skip-worktree'):
                git(repo, 'update-index', flag, 'tracked')
                (repo / 'tracked').write_text('change hidden from git diff')
                result = context.collect_repository_context(repo)
                self.assertFalse(result['complete'])
                self.assertTrue(result['identity']['stale'])
                git(repo, 'update-index', '--no-assume-unchanged', '--no-skip-worktree', 'tracked')
            (repo / 'new').write_text('data')
            with patch.object(context, '_hash_worktree_path', side_effect=context.SnapshotFailure('path-unreadable-or-changed')):
                result = context.collect_repository_context(repo)
            self.assertEqual(result['identity']['before'], result['identity']['after'])
            self.assertTrue(result['identity']['stale'])
            self.assertFalse(result['complete'])

    def test_non_repository_is_explicitly_incomplete_and_no_exception_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = context.collect_repository_context(tmp)
            self.assertTrue(result['identity']['stale'])
            self.assertFalse(result['complete'])
            self.assertFalse(result['identity']['before']['complete'])
        with patch.object(context.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['git'], 1, output=b'partial', stderr=b'token=canary')):
            result = context._run(['git', 'status'], Path('.'))
        self.assertEqual(result['exit_code'], 124)
        self.assertNotIn('canary', json.dumps(result))

    def test_cli_real_repository_cap_and_errors_include_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            initialize(repo)
            for n in range(60):
                (repo / ('path-' + str(n))).write_text('data')
            proc = subprocess.run([sys.executable, str(MODULE_PATH), '--repo', tmp, '--max-bytes', '2048'], capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertLessEqual(len(proc.stdout), 2048)
            self.assertFalse(json.loads(proc.stdout)['identity']['stale'])
            proc = subprocess.run([sys.executable, str(MODULE_PATH), '--repo', tmp, '--max-bytes', '128'], capture_output=True)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, b'')
            self.assertLessEqual(len(proc.stderr), 128)
            self.assertNotIn(tmp.encode(), proc.stderr)

    def test_history_is_closed_and_rejects_unsafe_source_fields(self):
        cases = [message(extra='raw'), message(role='reasoning'),
                 message(source={'id': 's', 'coordinate': '1', 'digest': 'd' * 64, 'raw': 'private'}),
                 message(source={'id': 'token=source-canary', 'coordinate': '1', 'digest': 'd' * 64}),
                 message(source={'id': 's', 'coordinate': '1', 'digest': 'not-a-digest'})]
        result = context.project_history_envelope(cases + [message(excerpt='token=excerpt-canary')])
        self.assertEqual(result['omissions']['malformed'], len(cases))
        self.assertEqual(len(result['items']), 1)
        self.assertNotIn('canary', json.dumps(result))

    def test_history_bound_accounts_for_newline_and_final_omission_digits(self):
        entries = [message(id=str(n), excerpt='界' * 20) for n in range(105)]
        for cap in (256, 550, 999):
            result = context.project_history_envelope(entries, max_bytes=cap)
            self.assertLessEqual(len(context._cli_encoded(result)), cap)
            self.assertEqual(len(result['items']) + result['omissions']['byte_limit'], len(entries))
        result = context.project_history_envelope([{'kind': 'reasoning', 'text': 'private'}, {'kind': 'tool', 'payload': 'private'}])
        self.assertEqual(result['omissions']['reasoning'], 1)
        self.assertEqual(result['omissions']['raw_tool_payload'], 1)

    def test_pr_pagination_is_complete_or_explicitly_failed_without_raw_errors(self):
        def fetch(cursor):
            if cursor is None:
                return {'nodes': [{'id': 'a', 'isResolved': False, 'isOutdated': True}],
                        'pageInfo': {'hasNextPage': True, 'endCursor': 'more'}}
            raise OSError('token=private-canary')
        result = context.project_pr_threads(fetch)
        self.assertFalse(result['pagination']['complete'])
        self.assertEqual(result['unresolved']['outdated'], ['a'])
        self.assertNotIn('canary', json.dumps(result))
        malformed = context.project_pr_threads(lambda _: {})
        self.assertFalse(malformed['pagination']['complete'])
        repeated = context.project_pr_threads(lambda _: {'nodes': [], 'pageInfo': {'hasNextPage': True, 'endCursor': 'same'}})
        self.assertFalse(repeated['pagination']['complete'])
        self.assertLessEqual(repeated['pagination']['pages'], 2)


if __name__ == '__main__':
    unittest.main()
