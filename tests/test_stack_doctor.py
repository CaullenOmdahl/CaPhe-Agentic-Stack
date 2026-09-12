import importlib.util
from pathlib import Path
import tempfile
import unittest
import os
import subprocess
from unittest import mock


PATH = Path(__file__).parents[1] / "tools" / "stack_doctor.py"
SPEC = importlib.util.spec_from_file_location("stack_doctor", PATH)
doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(doctor)


class DoctorContracts(unittest.TestCase):
    def test_inspect_is_read_only_and_reports_missing_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = doctor.inspect(root, runtime=root / "missing")
            self.assertIn("runtime_missing", result["unresolved"])
            self.assertEqual(list(root.iterdir()), [])

    def test_reports_source_digest_hook_path_and_managed_markers_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            runtime = root / "runtime"
            (runtime / "skills" / "a").mkdir(parents=True)
            (runtime / "VERSION").write_text("3\n")
            (runtime / "skills" / "a" / "SKILL.md").write_text("safe")
            repo = root / "repo"
            repo.mkdir()
            (repo / ".agent").mkdir()
            (repo / ".agent" / ".strict-version").write_text("3\n")
            result = doctor.inspect(repo, runtime=runtime, git_config=lambda key: "/hooks" if key == "core.hooksPath" else None)
            self.assertEqual(result["runtime"]["version"], "3")
            self.assertIsNone(result["runtime"]["source_digest"])
            self.assertEqual(result["hooks"]["effective_path"], "/hooks")
            self.assertFalse(result["project"]["managed"])
            self.assertIn("effective_gate_mismatch", result["unresolved"])
            self.assertNotIn("safe", str(result))

    def test_duplicate_skill_names_are_explicit_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for base in (root / "one", root / "two"):
                (base / "duplicate").mkdir(parents=True)
                (base / "duplicate" / "SKILL.md").write_text("x")
            result = doctor.find_duplicate_skills([root / "one", root / "two"])
            self.assertEqual(result["duplicate"], [str(root / "one" / "duplicate"), str(root / "two" / "duplicate")])

    def test_relative_effective_path_requires_exact_hook_gate_and_python_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); runtime = root / "runtime"; repo = root / "repo"
            hooks = repo / "relative-hooks"; hooks.mkdir(parents=True)
            canonical = runtime / "strict-mode/bin"; canonical.mkdir(parents=True)
            (repo / ".agent").mkdir(); (repo / ".agent/.strict-version").write_text("3\n")
            for name in doctor.HOOK_FILES:
                (canonical / name).write_text("expected-" + name)
                (hooks / name).write_text("expected-" + name)
                (hooks / name).chmod(0o755)
            report = lambda: doctor.inspect(repo, runtime=runtime, git_config=lambda key: "relative-hooks")
            self.assertTrue(report()["hooks"]["verified"])
            self.assertTrue(report()["project"]["managed"])
            for name in doctor.HOOK_FILES:
                original = (hooks / name).read_text()
                (hooks / name).write_text("stale")
                self.assertFalse(report()["hooks"]["verified"])
                self.assertFalse(report()["project"]["managed"])
                (hooks / name).write_text(original)
            (hooks / "pre-commit").chmod(0o644)
            self.assertFalse(report()["hooks"]["verified"])

    def test_marker_symlinks_and_invalid_versions_never_leak_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); runtime = root / "runtime"; repo = root / "repo"
            runtime.mkdir(); (repo / ".agent").mkdir(parents=True)
            secret = root / "secret"; secret.write_text("SECRET_CANARY")
            (repo / ".agent/.strict-version").symlink_to(secret)
            (runtime / "VERSION").write_text("SECRET_CANARY")
            result = doctor.inspect(repo, runtime=runtime)
            self.assertNotIn("SECRET_CANARY", str(result))
            self.assertFalse(result["project"]["managed"])

    def test_effective_git_hooks_ignore_inherited_foreign_repository_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = root / "repo"; wrong = root / "wrong"; runtime = root / "runtime"
            for path in (repo, wrong):
                path.mkdir(); subprocess.run(["git", "init", "-q", str(path)], check=True)
            hooks = repo / "owned-hooks"; hooks.mkdir()
            subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", str(hooks)], check=True)
            for name in doctor.HOOK_FILES:
                canonical = runtime / "strict-mode/bin" / name; canonical.parent.mkdir(parents=True, exist_ok=True)
                canonical.write_text(name); (hooks / name).write_text(name); (hooks / name).chmod(0o755)
            env = {"GIT_DIR": str(wrong / ".git"), "GIT_WORK_TREE": str(wrong), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/must-not-use"}
            with mock.patch.dict(os.environ, env):
                report = doctor.inspect(repo, runtime=runtime)
            self.assertEqual(report["hooks"]["effective_path"], str(hooks))
            self.assertTrue(report["hooks"]["verified"])
