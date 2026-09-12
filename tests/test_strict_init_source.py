from pathlib import Path
import importlib.util
import os
import json
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("strict_init_tested", ROOT / "strict-mode/bin/strict_init.py")
initializer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(initializer)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, text=True, capture_output=True).stdout.strip()


class StrictInitSourceTests(unittest.TestCase):
    def test_initializer_regression_suite(self):
        script = ROOT / "strict-mode/test/strict-init-refresh-test.sh"
        result = subprocess.run(["bash", str(script)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def repo(self, root):
        repo = root / "repo"; repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "user.email", "test@example.invalid")
        (repo / "README.md").write_text("test")
        git(repo, "add", "."); git(repo, "commit", "-qm", "initial")
        return repo

    def test_linked_worktree_migrates_config_and_preserves_main_effective_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); main = self.repo(root); child = root / "child"
            git(main, "worktree", "add", "-qb", "child", str(child))
            original = git(main, "rev-parse", "--git-path", "hooks")
            initializer.initialize(ROOT / "strict-mode", child)
            self.assertEqual(git(main, "rev-parse", "--show-toplevel"), str(main))
            self.assertEqual(git(child, "rev-parse", "--show-toplevel"), str(child))
            self.assertEqual(git(main, "rev-parse", "--git-path", "hooks"), original)
            self.assertEqual(git(main, "config", "--file", str(main / ".git/config.worktree"), "core.bare"), "false")
            self.assertTrue(Path(git(child, "config", "core.hooksPath")).is_dir())
            self.assertFalse((main / ".agent").exists())
            self.assertEqual(git(child, "check-ignore", ".agent/.strict-version"), ".agent/.strict-version")

    def test_common_core_worktree_is_migrated_without_changing_main_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            git(repo, "config", "core.worktree", str(repo))
            initializer.initialize(ROOT / "strict-mode", repo)
            self.assertEqual(git(repo, "rev-parse", "--show-toplevel"), str(repo))
            self.assertEqual(git(repo, "config", "--file", str(repo / ".git/config.worktree"), "core.worktree"), str(repo))
            result = subprocess.run(["git", "-C", str(repo), "config", "--local", "--get", "core.worktree"], capture_output=True)
            self.assertEqual(result.returncode, 1)

    def test_failure_restores_all_repository_files_config_and_hook_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); main = self.repo(root); child = root / "child"
            git(main, "worktree", "add", "-qb", "child", str(child))
            (child / "AGENTS.md").write_text("dirty user rules\n")
            def snapshot():
                return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o777) for p in root.rglob("*") if p.is_file()}
            before = snapshot()
            with self.assertRaises(initializer.InitError): initializer.initialize(ROOT / "strict-mode", child, fail_probe=True)
            self.assertEqual(snapshot(), before)
            self.assertFalse((child / ".agent").exists())
            self.assertEqual(git(main, "rev-parse", "--show-toplevel"), str(main))
            self.assertEqual(git(child, "rev-parse", "--show-toplevel"), str(child))

    def test_custom_relative_hook_path_exact_chain_arguments_and_other_hooks_survive_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            custom = repo / "hooks with ' quote $literal"; custom.mkdir()
            hook = custom / "pre-commit"
            hook.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$0" "$PWD" "$@" >> custom.log\n')
            hook.chmod(0o755)
            other = custom / "post-commit"
            other.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$0" "$PWD" "$@" >> other.log\n')
            other.chmod(0o755)
            original = hook.read_bytes()
            git(repo, "config", "core.hooksPath", custom.name)
            initializer.initialize(ROOT / "strict-mode", repo)
            initializer.initialize(ROOT / "strict-mode", repo)
            env = dict(os.environ, CAPHE_PREVIOUS_HOOK="/must/not/run")
            result = subprocess.run(["git", "hook", "run", "pre-commit", "--", "one two", "three"], cwd=repo, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((repo / "custom.log").read_text().splitlines(), [str(Path(custom.name) / "pre-commit"), str(repo), "one two", "three"])
            git(repo, "hook", "run", "post-commit", "--", "argument")
            self.assertEqual((repo / "other.log").read_text().splitlines(), [str(Path(custom.name) / "post-commit"), str(repo), "argument"])
            self.assertEqual(hook.read_bytes(), original)

    def test_symlinked_managed_child_preflights_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            (repo / ".agent").mkdir()
            outside = root / "outside"; outside.mkdir()
            (repo / ".agent/decisions").symlink_to(outside, target_is_directory=True)
            config = (repo / ".git/config").read_bytes()
            with self.assertRaises(initializer.InitError): initializer.initialize(ROOT / "strict-mode", repo)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual((repo / ".git/config").read_bytes(), config)
            self.assertFalse((repo / "AGENTS.md").exists())

    def test_only_untracked_off_first_line_preserves_disabled_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            (repo / ".agent").mkdir(); marker = repo / ".agent/.strict-mode"
            marker.write_text("off\nuser explanation\n")
            before = (repo / ".git/config").read_bytes()
            initializer.initialize(ROOT / "strict-mode", repo)
            self.assertEqual((repo / ".git/config").read_bytes(), before)
            self.assertFalse((repo / ".agent/.strict-version").exists())
            git(repo, "add", "-f", ".agent/.strict-mode")
            initializer.initialize(ROOT / "strict-mode", repo)
            self.assertEqual((repo / ".agent/.strict-version").read_text(), "3\n")
            self.assertEqual(marker.read_text(), "off\nuser explanation\n")
            self.assertEqual(git(repo, "ls-files", "--error-unmatch", ".agent/.strict-mode"), ".agent/.strict-mode")

    def test_inherited_git_env_is_ignored_but_global_hook_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            other_parent = root / "other"; other_parent.mkdir(); wrong = self.repo(other_parent)
            hooks = root / "global-hooks"; hooks.mkdir()
            (hooks / "pre-commit").write_text("#!/bin/sh\necho global-hook\n")
            (hooks / "pre-commit").chmod(0o755)
            global_config = root / "gitconfig"
            subprocess.run(["git", "config", "--file", str(global_config), "core.hooksPath", str(hooks)], check=True)
            before = (wrong / ".git/config").read_bytes()
            env = {"GIT_DIR": str(wrong / ".git"), "GIT_WORK_TREE": str(wrong), "GIT_INDEX_FILE": str(wrong / ".git/index"), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/must-not-use", "GIT_CONFIG_GLOBAL": str(global_config)}
            with mock.patch.dict(os.environ, env):
                initializer.initialize(ROOT / "strict-mode", repo)
            self.assertEqual((wrong / ".git/config").read_bytes(), before)
            self.assertFalse((wrong / ".agent").exists())
            hookdir = Path(git(repo, "config", "core.hooksPath"))
            self.assertIn(str(hooks / "pre-commit"), (hookdir / ".caphe-chain.sh").read_text())
            self.assertEqual((repo / ".agent/.strict-version").read_text(), "3\n")

    def test_refresh_rejects_changed_chain_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            original = repo / ".git/hooks/pre-commit"
            original.write_text("#!/bin/sh\nexit 0\n"); original.chmod(0o755)
            initializer.initialize(ROOT / "strict-mode", repo)
            hooks = Path(git(repo, "config", "core.hooksPath"))
            (hooks / ".caphe-chain.sh").write_text("CAPHE_PREVIOUS_HOOK=''\ntouch never-execute-this\n")
            before = {str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
            with self.assertRaises(initializer.InitError): initializer.initialize(ROOT / "strict-mode", repo)
            self.assertEqual({str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}, before)

    def test_chain_preserves_stdin_and_refresh_rejects_noncanonical_shell_even_with_updated_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            original = repo / ".git/hooks/pre-commit"
            original.write_text('#!/bin/sh\ncat > original-stdin\nprintf "%s\\n" "$@" > original-arguments\n')
            original.chmod(0o755)
            initializer.initialize(ROOT / "strict-mode", repo)
            hookdir = Path(git(repo, "config", "core.hooksPath"))
            run = subprocess.run([str(hookdir / "pre-commit"), "one two", "three"], cwd=repo, input="stdin canary\n", text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual((repo / "original-stdin").read_text(), "stdin canary\n")
            self.assertEqual((repo / "original-arguments").read_text().splitlines(), ["one two", "three"])
            chain = hookdir / ".caphe-chain.sh"
            chain.write_text(chain.read_text() + "touch never-execute-this\n")
            metadata = hookdir / ".caphe-activation.json"
            record = json.loads(metadata.read_text()); record["chain_sha256"] = hashlib.sha256(chain.read_bytes()).hexdigest()
            metadata.write_text(json.dumps(record))
            with self.assertRaises(initializer.InitError): initializer.initialize(ROOT / "strict-mode", repo)
            self.assertFalse((repo / "never-execute-this").exists())

    def test_refresh_rejects_missing_or_open_metadata(self):
        for mutation in ("missing", "extra-field", "duplicate-field", "target-change"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); repo = self.repo(root)
                original = repo / ".git/hooks/pre-commit"
                original.write_text("#!/bin/sh\nexit 0\n"); original.chmod(0o755)
                initializer.initialize(ROOT / "strict-mode", repo)
                metadata = Path(git(repo, "config", "core.hooksPath")) / ".caphe-activation.json"
                if mutation == "missing": metadata.unlink()
                elif mutation == "extra-field":
                    value = json.loads(metadata.read_text()); value["untrusted"] = True; metadata.write_text(json.dumps(value))
                elif mutation == "duplicate-field":
                    metadata.write_text(metadata.read_text().replace('{', '{"schema":1,', 1))
                else: original.write_text("#!/bin/sh\nexit 2\n")
                before = {str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
                with self.assertRaises(initializer.InitError): initializer.initialize(ROOT / "strict-mode", repo)
                self.assertEqual({str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}, before)

    def test_only_exact_known_framework_wrapper_is_not_chained(self):
        wrapper = b'#!/usr/bin/env bash\nset -euo pipefail\nexec "$HOME/strict-mode/bin/strict-green-gate.sh" --mode affected\n'
        self.assertEqual(len(wrapper), 104)
        self.assertEqual(hashlib.sha256(wrapper).hexdigest(), initializer.LEGACY_WRAPPER_SHA256)
        for suffix in (b"", b"# custom comment\n", b"echo custom command\n", b"# STRICT-MODE:MANAGED-HOOK v3\n"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); repo = self.repo(root)
                original = repo / ".git/hooks/pre-commit"
                original.write_bytes(wrapper + suffix); original.chmod(0o755)
                initializer.initialize(ROOT / "strict-mode", repo)
                metadata = Path(git(repo, "config", "core.hooksPath")) / ".caphe-activation.json"
                record = json.loads(metadata.read_text())
                self.assertEqual(record["previous_hook"] is not None, bool(suffix))
                self.assertEqual(original.read_bytes(), wrapper + suffix)

    def test_accepted_custom_hook_update_reconciles_via_original_directory_and_normal_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = self.repo(root)
            original = repo / ".git/hooks/pre-commit"
            original.write_text("#!/bin/sh\nexit 0\n"); original.chmod(0o755)
            initializer.initialize(ROOT / "strict-mode", repo)
            managed = Path(git(repo, "config", "core.hooksPath"))
            record = json.loads((managed / initializer.ACTIVATION_FILE).read_text())
            original.write_text("#!/bin/sh\n# accepted custom update\nexit 0\n")
            with self.assertRaises(initializer.InitError): initializer.initialize(ROOT / "strict-mode", repo)
            # Explicitly select the recorded original directory after reviewing the change.
            original_directory = str(Path(record["previous_hook"]["path"]).parent)
            git(repo, "config", "--worktree", "core.hooksPath", original_directory)
            initializer.initialize(ROOT / "strict-mode", repo)
            refreshed = initializer.read_activation(repo, managed, canon=ROOT / "strict-mode")
            self.assertEqual(refreshed["previous_hook"]["sha256"], hashlib.sha256(original.read_bytes()).hexdigest())
            self.assertIn("accepted custom update", original.read_text())


if __name__ == "__main__":
    unittest.main()
