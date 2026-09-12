import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("gate_runtime", ROOT / "strict-mode/bin/strict_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def repository(path):
    env = os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    for args in (("init", "-q"), ("config", "user.email", "test@example.invalid"),
                 ("config", "user.name", "Test")):
        subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True)
    (path / "tracked.txt").write_text("baseline")
    (path / "second.txt").write_text("baseline")
    subprocess.run(["git", "add", "."], cwd=path, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, env=env, check=True)


class RuntimeTests(unittest.TestCase):
    def test_cli_and_wrapper_bind_invoking_checkout_despite_inherited_git_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            intended, other = base / 'intended', base / 'other'
            for root, code in ((intended, 7), (other, 0)):
                root.mkdir(); repository(root); (root / '.agent').mkdir()
                manifest = {'version': 1, 'components': [{'name': 'fixture', 'paths': ['**'],
                    'commands': [{'name': 'check', 'run': [sys.executable, '-c', f'raise SystemExit({code})']}]}]}
                (root / '.agent/strict-gate.json').write_text(json.dumps(manifest))
            environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
            environment.update(GIT_DIR=str(other / '.git'), GIT_WORK_TREE=str(other),
                               GIT_INDEX_FILE=str(other / '.git/index'), GIT_CONFIG_GLOBAL=os.devnull,
                               GIT_CONFIG_NOSYSTEM='1')
            commands = ((sys.executable, str(ROOT / 'strict-mode/bin/strict_gate.py')),
                        ('bash', str(ROOT / 'strict-mode/bin/strict-green-gate.sh')))
            for disabled in (False, True):
                if disabled:
                    (other / '.agent/.strict-mode').write_text('off\n')
                for command in commands:
                    with self.subTest(command=command[0], other_disabled=disabled):
                        result = subprocess.run([*command, '--mode', 'completion'], cwd=intended,
                                                env=environment, capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        self.assertIn('FAIL  fixture:check', result.stderr)
                        self.assertNotIn('user-disabled', result.stdout)

    def test_declared_order_prevents_checks_racing_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            data = {"version": 1, "components": [{"name": "app", "paths": ["**"], "commands": [
                {"name": "prepare", "run": [sys.executable, "-c", "import time; time.sleep(.1)"]},
                {"name": "test", "run": [sys.executable, "-c", "pass"]},
            ]}]}
            plan = gate.build_plan(data, [], mode="completion")
            self.assertEqual(plan[1].after, ("app:prepare",))

    def test_failed_preparation_blocks_dependent_checks(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp)
            repository(root)
            report_path = Path(private).resolve() / "report.json"
            data = {"version": 1, "components": [{"name": "app", "paths": ["**"], "commands": [
                {"name": "prepare", "run": [sys.executable, "-c", "raise SystemExit(9)"]},
                {"name": "test", "run": [sys.executable, "-c", "from pathlib import Path; Path('ran-test').touch()"]},
            ]}]}
            plan = gate.build_plan(data, [], mode="completion")
            self.assertEqual(gate.execute_plan(root, plan, "manifest", 4, report_path=report_path), 1)
            self.assertFalse((root / "ran-test").exists())
            outcomes = json.loads(report_path.read_text())["commands"]
            self.assertEqual(outcomes[1]["exit_code"], 126)

    def test_parallel_requires_explicit_declaration(self):
        data = {"version": 1, "components": [{"name": "app", "paths": ["**"], "commands": [
            {"name": "one", "run": ["true"], "parallel_safe": True},
            {"name": "two", "run": ["true"], "parallel_safe": True},
        ]}]}
        self.assertTrue(all(not item.after for item in gate.build_plan(data, [], mode="completion")))

    def test_changed_paths_include_all_executed_working_state_and_unusual_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            (root / "tracked.txt").write_text("staged")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            (root / "second.txt").write_text("unstaged")
            (root / "odd\nname.txt").write_text("untracked")
            self.assertEqual(set(gate.changed_paths(root)), {"tracked.txt", "second.txt", "odd\nname.txt"})

    def test_snapshot_changes_without_a_new_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            first = gate.snapshot_identity(root)
            (root / "tracked.txt").write_text("changed")
            second = gate.snapshot_identity(root)
            self.assertEqual(first["revision"], second["revision"])
            self.assertNotEqual(first["snapshot_digest"], second["snapshot_digest"])
            self.assertFalse(first["dirty"])
            self.assertTrue(second["dirty"])

    def test_hidden_git_flags_block_full_gate_before_any_command_runs(self):
        for flag in ('--assume-unchanged', '--skip-worktree'):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repository(root)
                subprocess.run(['git', 'update-index', flag, 'tracked.txt'], cwd=root, check=True)
                command = gate.CommandSpec('fixture', 'mutates',
                    (sys.executable, '-c', "from pathlib import Path; Path('tracked.txt').write_text('changed')"))
                with self.assertRaisesRegex(gate.ManifestError, 'hidden|assume|skip'):
                    gate.execute_plan(root, [command], 'manifest', 1, mode='completion')
                self.assertEqual((root / 'tracked.txt').read_text(), 'baseline')

    def add_gitlink(self, root, name="module"):
        module = root / name
        module.mkdir(parents=True)
        repository(module)
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=module, text=True).strip()
        subprocess.run(['git', 'update-index', '--add', '--cacheinfo', '160000,' + revision + ',' + name], cwd=root, check=True)
        return module

    def ignore_cache(self, root):
        (root / ".gitignore").write_text(".agent/cache/\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "ignore cache"], cwd=root, check=True)

    def test_nested_gitlinks_bind_dirty_and_untracked_state_despite_ignore_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            nested = self.add_gitlink(module, 'nested')
            (root / '.gitignore').write_text('module/\n')
            (module / '.gitignore').write_text('nested/\n.env\n')
            (module / '.env').write_text('ignored state')
            for node in (root, module):
                subprocess.run(['git', 'config', 'diff.ignoreSubmodules', 'all'], cwd=node, check=True)
                subprocess.run(['git', 'config', 'submodule.module.ignore', 'all'], cwd=node, check=True)
            before = gate.snapshot_identity(root)
            (nested / 'tracked.txt').write_text('dirty A')
            dirty = gate.snapshot_identity(root)
            (nested / 'tracked.txt').write_text('dirty B')
            dirtier = gate.snapshot_identity(root)
            (nested / 'new.txt').write_text('new A')
            new = gate.snapshot_identity(root)
            (nested / 'new.txt').write_text('new B')
            newer = gate.snapshot_identity(root)
            (nested / 'new.txt').chmod(0o700)
            executable = gate.snapshot_identity(root)
            (nested / 'link').symlink_to('new.txt')
            link = gate.snapshot_identity(root)
            (nested / 'link').unlink()
            (nested / 'link').symlink_to('tracked.txt')
            relink = gate.snapshot_identity(root)
            identities = [before, dirty, dirtier, new, newer, executable, link, relink]
            self.assertEqual(len({item['snapshot_digest'] for item in identities}), len(identities))
            (module / '.env').write_text('different ignored state')
            self.assertEqual(relink, gate.snapshot_identity(root))

    def test_initialized_submodule_gitfile_overrides_ignore_config(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as source:
            root = Path(tmp)
            repository(root)
            repository(Path(source))
            subprocess.run(['git', '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', source, 'module'],
                           cwd=root, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-qm', 'submodule'], cwd=root, check=True)
            subprocess.run(['git', 'config', 'diff.ignoreSubmodules', 'all'], cwd=root, check=True)
            subprocess.run(['git', 'config', 'submodule.module.ignore', 'all'], cwd=root, check=True)
            self.assertTrue((root / 'module' / '.git').is_file())
            clean = gate.snapshot_identity(root)
            self.assertFalse(clean['dirty'])
            (root / 'module' / 'tracked.txt').write_text('nested change')
            dirty = gate.snapshot_identity(root)
            self.assertTrue(dirty['dirty'])
            self.assertNotEqual(clean['snapshot_digest'], dirty['snapshot_digest'])
            self.assertIn('module', gate.changed_paths(root))

    def test_gitlink_binds_staged_identity_and_nested_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            first = gate.snapshot_identity(root)
            subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'new head'], cwd=module, check=True)
            new_head = gate.snapshot_identity(root)
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=module, text=True).strip()
            subprocess.run(['git', 'update-index', '--cacheinfo', '160000,' + revision + ',module'], cwd=root, check=True)
            staged = gate.snapshot_identity(root)
            self.assertNotEqual(first['snapshot_digest'], new_head['snapshot_digest'])
            self.assertNotEqual(new_head['snapshot_digest'], staged['snapshot_digest'])
            (module / 'tracked.txt').write_text('staged content')
            subprocess.run(['git', 'add', 'tracked.txt'], cwd=module, check=True)
            (module / 'tracked.txt').write_text('baseline')
            self.assertNotEqual(staged['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_absent_gitlink_is_bound_and_staged_deletion_keeps_checkout_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            subprocess.run(['git', 'commit', '-qm', 'gitlink'], cwd=root, check=True)
            present = gate.snapshot_identity(root)
            shutil.rmtree(module)
            absent = gate.snapshot_identity(root)
            self.assertNotEqual(present['snapshot_digest'], absent['snapshot_digest'])
            self.assertEqual(absent, gate.snapshot_identity(root))
            module = root / 'replacement'
            module.mkdir()
            repository(module)
            module.rename(root / 'module')
            subprocess.run(['git', 'update-index', '--force-remove', 'module'], cwd=root, check=True)
            (root / '.gitignore').write_text('module/\n')
            deleted = gate.snapshot_identity(root)
            (root / 'module' / 'tracked.txt').write_text('still executed')
            self.assertNotEqual(deleted['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_unstaged_file_directory_replacement_binds_presence_contents_and_reversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            path = root / 'tracked.txt'
            original = gate.snapshot_identity(root)
            path.unlink()
            absent = gate.snapshot_identity(root)
            path.mkdir()
            empty = gate.snapshot_identity(root)
            self.assertNotEqual(absent['snapshot_digest'], empty['snapshot_digest'])
            (path / 'source.txt').write_text('source A')
            populated = gate.snapshot_identity(root)
            (path / 'source.txt').write_text('source B')
            edited = gate.snapshot_identity(root)
            self.assertNotEqual(empty['snapshot_digest'], populated['snapshot_digest'])
            self.assertNotEqual(populated['snapshot_digest'], edited['snapshot_digest'])
            shutil.rmtree(path)
            path.write_text('baseline')
            self.assertEqual(original, gate.snapshot_identity(root))
            subprocess.run(['git', 'update-index', '--force-remove', 'tracked.txt'], cwd=root, check=True)
            path.unlink()
            path.mkdir()
            (path / 'source.txt').write_text('tracked child')
            subprocess.run(['git', 'add', 'tracked.txt'], cwd=root, check=True)
            subprocess.run(['git', 'commit', '-qm', 'directory'], cwd=root, check=True)
            directory = gate.snapshot_identity(root)
            shutil.rmtree(path)
            path.write_text('replacement file')
            file = gate.snapshot_identity(root)
            self.assertNotEqual(directory['snapshot_digest'], file['snapshot_digest'])
            path.write_text('edited replacement file')
            self.assertNotEqual(file['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_unstaged_file_directory_replacement_preserves_ignored_content_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            (root / '.gitignore').write_text('.env\nignored/\n')
            path = root / 'tracked.txt'
            path.unlink()
            path.mkdir()
            empty = gate.snapshot_identity(root)
            (path / '.env').write_text('ignored A')
            (path / 'ignored').mkdir()
            (path / 'ignored' / 'local.txt').write_text('local A')
            self.assertEqual(empty, gate.snapshot_identity(root))
            (path / '.env').write_text('ignored B')
            self.assertEqual(empty, gate.snapshot_identity(root))
            (path / 'source.txt').write_text('executed')
            self.assertNotEqual(empty['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_unstaged_file_directory_replacement_nested_mutation_blocks_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            path = root / 'tracked.txt'
            path.unlink()
            path.mkdir()
            (path / 'source.txt').write_text('before')
            command = gate.CommandSpec('fixture', 'mutates', (sys.executable, '-c',
                "from pathlib import Path; Path('tracked.txt/source.txt').write_text('after')"))
            self.assertEqual(gate.execute_plan(root, [command], 'manifest', 1, mode='completion'), 1)
            self.assertEqual((path / 'source.txt').read_text(), 'after')

    def test_staged_gitlink_replacement_with_regular_file_binds_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            subprocess.run(['git', 'commit', '-qm', 'gitlink'], cwd=root, check=True)
            shutil.rmtree(module)
            module.write_text('replacement A')
            subprocess.run(['git', 'add', 'module'], cwd=root, check=True)
            before = gate.snapshot_identity(root)
            module.write_text('replacement B')
            self.assertNotEqual(before['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_staged_gitlink_replacement_with_directory_binds_tracked_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            subprocess.run(['git', 'commit', '-qm', 'gitlink'], cwd=root, check=True)
            shutil.rmtree(module)
            module.mkdir()
            (module / 'source.txt').write_text('replacement A')
            subprocess.run(['git', 'update-index', '--force-remove', 'module'], cwd=root, check=True)
            subprocess.run(['git', 'add', 'module'], cwd=root, check=True)
            before = gate.snapshot_identity(root)
            (module / 'source.txt').write_text('replacement B')
            self.assertNotEqual(before['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_staged_gitlink_replacement_with_symlink_binds_target_without_following_it(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            subprocess.run(['git', 'commit', '-qm', 'gitlink'], cwd=root, check=True)
            shutil.rmtree(module)
            target = Path(outside)
            (target / 'private.txt').write_text('outside A')
            module.symlink_to(target, target_is_directory=True)
            subprocess.run(['git', 'add', 'module'], cwd=root, check=True)
            before = gate.snapshot_identity(root)
            (target / 'private.txt').write_text('outside B')
            self.assertEqual(before, gate.snapshot_identity(root))
            module.unlink()
            module.symlink_to(root, target_is_directory=True)
            self.assertNotEqual(before['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_uninitialized_empty_gitlink_is_distinct_from_absent_and_ordinary_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            shutil.rmtree(module)
            absent = gate.snapshot_identity(root)
            module.mkdir()
            empty = gate.snapshot_identity(root)
            self.assertNotEqual(absent['snapshot_digest'], empty['snapshot_digest'])
            self.assertEqual(empty, gate.snapshot_identity(root))
            (root / '.git/info/exclude').write_text('module/.env\n')
            (module / '.env').write_text('must not be read')
            ordinary = gate.snapshot_identity(root)
            self.assertNotEqual(empty['snapshot_digest'], ordinary['snapshot_digest'])
            (module / '.env').write_text('ignored local state changed')
            self.assertEqual(ordinary, gate.snapshot_identity(root))

    def test_untracked_nested_git_root_binds_its_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = root / 'module'
            module.mkdir()
            repository(module)
            before = gate.snapshot_identity(root)
            (module / 'tracked.txt').write_text('changed')
            self.assertNotEqual(before['snapshot_digest'], gate.snapshot_identity(root)['snapshot_digest'])

    def test_invalid_or_symlink_git_metadata_fail_closed(self):
        for kind in ('invalid-git', 'metadata-symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repository(root)
                module = self.add_gitlink(root)
                shutil.rmtree(module)
                if kind == 'invalid-git':
                    module.mkdir()
                    (module / '.git').write_text('invalid Git metadata')
                else:
                    module.mkdir()
                    (module / '.git').symlink_to(root / '.git', target_is_directory=True)
                with self.assertRaisesRegex(gate.ManifestError, 'Git|git|symlink'):
                    gate.snapshot_identity(root)

    def test_nested_hidden_flags_fail_closed(self):
        for flag in ('--assume-unchanged', '--skip-worktree'):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repository(root)
                module = self.add_gitlink(root)
                subprocess.run(['git', 'update-index', flag, 'tracked.txt'], cwd=module, check=True)
                with self.assertRaisesRegex(gate.ManifestError, 'hidden|assume|skip'):
                    gate.snapshot_identity(root)

    def test_nested_depth_and_git_metadata_cycles_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            module = self.add_gitlink(root)
            self.add_gitlink(module, 'nested')
            with mock.patch.object(gate, 'MAX_SNAPSHOT_DEPTH', 1):
                with self.assertRaisesRegex(gate.ManifestError, 'depth'):
                    gate.snapshot_identity(root)
            with self.assertRaisesRegex(gate.ManifestError, 'cycle'):
                gate._snapshot_identity(root, ((root / '.git').resolve(),))

    def test_clean_nested_gate_runs_and_nested_mutation_cannot_report_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            self.add_gitlink(root)
            command = gate.CommandSpec('fixture', 'pass', (sys.executable, '-c', 'pass'))
            self.assertEqual(gate.execute_plan(root, [command], 'manifest', 1, mode='completion'), 0)
            command = command._replace(argv=(sys.executable, '-c',
                "from pathlib import Path; Path('module/tracked.txt').write_text('changed')"))
            self.assertEqual(gate.execute_plan(root, [command], 'manifest', 1, mode='completion'), 1)

    def test_affected_cache_binds_file_mode_as_well_as_content(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            root = Path(tmp)
            (root / 'input').write_text('same bytes')
            (root / 'input').chmod(0o600)
            command = gate.CommandSpec('fixture', 'mode-sensitive',
                (sys.executable, '-c', "from pathlib import Path; raise SystemExit(9 if Path('input').stat().st_mode & 0o111 else 0)"),
                cache_allowed=True, cache_inputs=('input',), toolchain=((sys.executable, '--version'),))
            first = gate._run_one(root, command, 'manifest', Path(cache))
            self.assertEqual(first[1], 0)
            (root / 'input').chmod(0o700)
            second = gate._run_one(root, command, 'manifest', Path(cache))
            self.assertEqual(second[1], 9)
            self.assertFalse(second[3])

    def test_cache_rejects_symlink_inputs_and_symlinked_parents(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root, other = Path(tmp), Path(outside)
            (other / 'input').write_text('bytes')
            (root / 'link').symlink_to(other / 'input')
            (root / 'linked-parent').symlink_to(other, target_is_directory=True)
            for pattern in ('link', 'linked-parent/input'):
                command = gate.CommandSpec('fixture', 'cache', (sys.executable, '-c', 'pass'),
                    cache_allowed=True, cache_inputs=(pattern,), toolchain=((sys.executable, '--version'),))
                with self.subTest(pattern=pattern), self.assertRaisesRegex(gate.ManifestError, 'symlink'):
                    gate.cache_key(root, command, 'manifest')

    def test_failed_toolchain_probe_never_authorizes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').write_text('bytes')
            command = gate.CommandSpec('fixture', 'cache', (sys.executable, '-c', 'pass'),
                cache_allowed=True, cache_inputs=('input',),
                toolchain=((sys.executable, '-c', "print('same version'); raise SystemExit(7)"),))
            with self.assertRaisesRegex(gate.ManifestError, 'toolchain'):
                gate.cache_key(root, command, 'manifest')

    def test_missing_command_is_a_failed_outcome_not_an_unhandled_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = gate.CommandSpec("fixture", "missing", ("caphe-nonexistent-command",))
            _, code, output, cached = gate._run_one(Path(tmp), command, "manifest", Path(tmp) / "cache")
            self.assertEqual(code, 127)
            self.assertFalse(cached)
            self.assertTrue(output)

    def test_timeout_is_a_failed_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = gate.CommandSpec("fixture", "timeout", (sys.executable, "-c", "import time; time.sleep(10)"), timeout_seconds=0.05)
            _, code, output, _ = gate._run_one(Path(tmp), command, "manifest", Path(tmp) / "cache")
            self.assertEqual(code, 124)
            self.assertIn("timeout", output.lower())

    def test_diagnostic_report_preserves_failure_and_is_not_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            root = Path(tmp)
            repository(root)
            path = Path(state).resolve() / "report.json"
            command = gate.CommandSpec("fixture", "fails", (sys.executable, "-c", "raise SystemExit(9)"))
            code = gate.execute_plan(root, [command], "manifest", 1, report_path=path, mode="completion")
            report = json.loads(path.read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report["commands"][0]["exit_code"], 9)
            self.assertFalse(report["authoritative"])
            self.assertEqual(report["mode"], "completion")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_source_changed_by_a_command_cannot_be_reported_green(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            root = Path(tmp)
            repository(root)
            path = Path(state).resolve() / "report.json"
            command = gate.CommandSpec("fixture", "mutates", (sys.executable, "-c", "from pathlib import Path; Path('tracked.txt').write_text('mutated')"))
            code = gate.execute_plan(root, [command], "manifest", 1, report_path=path, mode="completion")
            self.assertNotEqual(code, 0)
            self.assertTrue(json.loads(path.read_text())["stale_source"])

    def test_stale_source_does_not_publish_a_cache_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            self.ignore_cache(root)
            command = gate.CommandSpec(
                "fixture", "mutates",
                (sys.executable, "-c", "from pathlib import Path; Path('tracked.txt').write_text('mutated')"),
                cache_allowed=True, cache_inputs=("tracked.txt",),
                toolchain=((sys.executable, "--version"),),
            )
            self.assertEqual(gate.execute_plan(root, [command], "manifest", 1), 1)
            (root / "tracked.txt").write_text("baseline")
            self.assertEqual(gate.execute_plan(root, [command], "manifest", 1), 1)
            self.assertEqual((root / "tracked.txt").read_text(), "mutated")

    def test_stable_source_publishes_and_reuses_an_ignored_cache_marker(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            root = Path(tmp)
            repository(root)
            self.ignore_cache(root)
            ran = Path(state) / "ran"
            command = gate.CommandSpec(
                "fixture", "passes",
                (sys.executable, "-c", f"from pathlib import Path; Path({str(ran)!r}).write_text('ran')"),
                cache_allowed=True, cache_inputs=("tracked.txt",),
                toolchain=((sys.executable, "--version"),),
            )
            before = gate.snapshot_identity(root)
            self.assertEqual(gate.execute_plan(root, [command], "manifest", 1), 0)
            self.assertEqual(before, gate.snapshot_identity(root))
            self.assertTrue(any((root / ".agent/cache/strict-gate").glob("*.ok")))
            ran.unlink()
            self.assertEqual(gate.execute_plan(root, [command], "manifest", 1), 0)
            self.assertFalse(ran.exists())

    def test_stable_source_does_not_publish_an_unignored_cache_marker(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            root = Path(tmp)
            repository(root)
            ran = Path(state) / "ran"
            command = gate.CommandSpec(
                "fixture", "passes",
                (sys.executable, "-c", f"from pathlib import Path; Path({str(ran)!r}).write_text('ran')"),
                cache_allowed=True, cache_inputs=("tracked.txt",),
                toolchain=((sys.executable, "--version"),),
            )
            before = gate.snapshot_identity(root)
            self.assertEqual(gate.execute_plan(root, [command], "manifest", 1), 0)
            self.assertEqual(before, gate.snapshot_identity(root))
            self.assertFalse((root / ".agent/cache/strict-gate").exists())
            ran.unlink()
            self.assertEqual(gate.execute_plan(root, [command], "manifest", 1), 0)
            self.assertTrue(ran.exists())

    def test_reports_reject_hidden_or_malformed_destination_repositories(self):
        for kind in ("malformed-config", "bare", "discovery-ceiling"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as destination:
                root = Path(source).resolve(); repository(root)
                other = Path(destination).resolve()
                if kind == "bare":
                    subprocess.run(["git", "init", "--bare", "-q", str(other)], check=True)
                else:
                    repository(other)
                    if kind == "malformed-config":
                        (other / ".git/config").write_text("[broken\n")
                nested = other / "nested"; nested.mkdir(mode=0o700)
                target = nested / "private" / "report.json"
                with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(other)}):
                    with self.assertRaises(gate.ManifestError):
                        gate.execute_plan(root, [], "manifest", 1, report_path=target, mode="completion")
                self.assertFalse(target.parent.exists())

    def test_report_unknown_git_discovery_fails_before_creating_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve() / "private" / "report.json"
            result = subprocess.CompletedProcess([], 128, "", "fatal: bad config line 1\n")
            with mock.patch.object(gate.subprocess, "run", return_value=result):
                with self.assertRaises(gate.ManifestError):
                    gate._report_destination(target)
            self.assertFalse(target.parent.exists())

    def test_reports_cannot_write_into_the_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository(root)
            command = gate.CommandSpec("fixture", "pass", (sys.executable, "-c", "pass"))
            with self.assertRaises(gate.ManifestError):
                gate.execute_plan(root, [command], "manifest", 1, report_path=root / "report.json", mode="completion")
            self.assertFalse((root / "report.json").exists())

    def test_reports_reject_canonical_records_after_lexical_normalization_and_casefold(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            for record in ("MeMoRiEs", "SeSsIoNs"):
                target = base / ".codex" / "scratch" / ".." / record / "report.json"
                with self.subTest(record=record), self.assertRaisesRegex(gate.ManifestError, "canonical records"):
                    gate._report_destination(target)
                self.assertFalse((base / ".codex" / record).exists())

    def test_reports_reject_original_symlink_path_before_lexical_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            (base / "link").symlink_to(base, target_is_directory=True)
            target = base / "link" / ".." / "private" / "report.json"
            with self.assertRaisesRegex(gate.ManifestError, "symlink"):
                gate._report_destination(target)
            self.assertFalse((base / "private").exists())

    def test_reports_reject_symlink_exposed_by_normalizing_missing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            records = base / '.codex' / 'memories'
            records.mkdir(parents=True, mode=0o700)
            (base / 'alias').symlink_to(records, target_is_directory=True)
            target = base / 'missing' / '..' / 'alias' / 'report.json'
            with self.assertRaisesRegex(gate.ManifestError, 'symlink'):
                gate._report_destination(target)
            self.assertFalse((records / 'report.json').exists())


if __name__ == "__main__":
    unittest.main()
