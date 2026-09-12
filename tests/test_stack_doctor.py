import importlib.util
from pathlib import Path
import tempfile
import unittest
import os
import json
import subprocess
from unittest import mock


PATH = Path(__file__).parents[1] / "tools" / "stack_doctor.py"
SPEC = importlib.util.spec_from_file_location("stack_doctor", PATH)
doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(doctor)


ACTIVATION_SPEC = importlib.util.spec_from_file_location("doctor_chain_fixture", PATH.parents[1] / "strict-mode/bin/strict_init.py")
activation = importlib.util.module_from_spec(ACTIVATION_SPEC)
ACTIVATION_SPEC.loader.exec_module(activation)


def install_empty_chain(repo, hooks, runtime):
    record = activation.activation_record(repo, hooks, runtime / "strict-mode", None)
    (hooks / activation.CHAIN_FILE).write_bytes(activation.chain_bytes(None))
    (hooks / activation.ACTIVATION_FILE).write_text(json.dumps(record))


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

    def test_initialize_project_and_doctor_agree_for_root_and_subdirectory(self):
        installer = doctor._installer()
        for from_child in (False, True):
            with self.subTest(from_child=from_child), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp).resolve()
                repo, wrong = base / "repo", base / "wrong"
                for target in (repo, wrong):
                    subprocess.run(["git", "init", "-q", str(target)], check=True)
                child = repo / "packages" / "app"
                child.mkdir(parents=True)
                original_foreign_config = (wrong / ".git/config").read_bytes()
                contamination = {
                    "GIT_DIR": str(wrong / ".git"), "GIT_WORK_TREE": str(wrong),
                    "GIT_INDEX_FILE": str(wrong / ".git/index"), "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/must-not-use",
                }
                with mock.patch.dict(os.environ, contamination):
                    result = installer.initialize_project(PATH.parents[1], child if from_child else repo, apply=True)
                    at_root = doctor.inspect(repo, runtime=PATH.parents[1])
                    at_child = doctor.inspect(child, runtime=PATH.parents[1])
                self.assertEqual(result["state"], "initialized")
                self.assertEqual(at_root, at_child)
                self.assertEqual(at_child["project"]["path"], str(repo))
                self.assertTrue(at_child["project"]["managed"])
                self.assertTrue(at_child["instructions"]["verified"])
                self.assertFalse((child / ".agent").exists())
                self.assertEqual((wrong / ".git/config").read_bytes(), original_foreign_config)
                self.assertFalse((wrong / ".agent").exists())

    def test_git_root_probe_failure_is_reported_without_claiming_management(self):
        failures = (FileNotFoundError("git unavailable"), subprocess.TimeoutExpired(["git"], 30))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with mock.patch.object(doctor.subprocess, "run", side_effect=failure):
                    result = doctor.inspect(root, runtime=root / "missing")
                self.assertFalse(result["project"]["managed"])
                self.assertIn("project_not_git", result["unresolved"])
                self.assertEqual(result["project"]["path"], str(root))
                self.assertEqual(list(root.iterdir()), [])

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
            install_empty_chain(repo, hooks, runtime)
            report = lambda: doctor.inspect(repo, runtime=runtime, git_config=lambda key: "relative-hooks")
            self.assertTrue(report()["hooks"]["verified"])
            self.assertFalse(report()["project"]["managed"])
            self.assertIn("managed_instructions_mismatch", report()["unresolved"])
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

    def test_invalid_utf8_version_markers_produce_structured_diagnostics(self):
        for malformed in ("runtime", "project"):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); runtime = root / "runtime"; repo = root / "repo"
                runtime.mkdir(); (repo / ".agent").mkdir(parents=True)
                versions = {"runtime": runtime / "VERSION", "project": repo / ".agent/.strict-version"}
                (runtime / ".caphe-runtime.json").write_text("{}")
                for path in versions.values():
                    path.write_bytes(b"3\n")
                versions[malformed].write_bytes(b"\xffSECRET_CANARY\n")
                before = {path: path.read_bytes() for path in versions.values()}
                report = doctor.inspect(repo, runtime=runtime)
                field = "version" if malformed == "runtime" else "managed_version"
                self.assertEqual(report[malformed][field], "invalid")
                self.assertIn(malformed + "_version_mismatch", report["unresolved"])
                self.assertFalse(report["project"]["managed"])
                self.assertNotIn("SECRET_CANARY", str(report))
                self.assertEqual({path: path.read_bytes() for path in versions.values()}, before)
                versions[malformed].write_bytes(b"3\r\n")
                self.assertEqual(doctor.inspect(repo, runtime=runtime)[malformed][field], "3")

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
            install_empty_chain(repo, hooks, runtime)
            env = {"GIT_DIR": str(wrong / ".git"), "GIT_WORK_TREE": str(wrong), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/must-not-use"}
            with mock.patch.dict(os.environ, env):
                report = doctor.inspect(repo, runtime=runtime)
            self.assertEqual(report["hooks"]["effective_path"], str(hooks))
            self.assertTrue(report["hooks"]["verified"])

    def test_missing_marker_or_changed_managed_instruction_fails_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); runtime = root / "runtime"; repo = root / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            hooks = repo / "hooks"; hooks.mkdir()
            template = (PATH.parents[1] / "strict-mode/templates/instruction-section.md").read_text()
            canonical = runtime / "strict-mode/templates/instruction-section.md"
            canonical.parent.mkdir(parents=True); canonical.write_text(template)
            for name in doctor.HOOK_FILES:
                source = runtime / "strict-mode/bin" / name; source.parent.mkdir(exist_ok=True)
                source.write_text(name); (hooks / name).write_text(name); (hooks / name).chmod(0o755)
            for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
                (repo / name).write_text("Custom rule preserved.\n" + template)
            install_empty_chain(repo, hooks, runtime)
            report = lambda: doctor.inspect(repo, runtime=runtime, git_config=lambda key: "hooks")
            self.assertIn("project_version_missing", report()["unresolved"])
            (repo / ".agent").mkdir(); (repo / ".agent/.strict-version").write_text("3\n")
            self.assertTrue(report()["project"]["managed"])
            self.assertTrue(report()["instructions"]["verified"])
            (repo / "CLAUDE.md").write_text("Changed instructions\n")
            self.assertFalse(report()["project"]["managed"])
            self.assertIn("managed_instructions_mismatch", report()["unresolved"])
            (repo / "CLAUDE.md").unlink(); (repo / "CLAUDE.md").symlink_to("AGENTS.md")
            self.assertTrue(report()["instructions"]["verified"])
            outside = root / "outside"; outside.write_text(template)
            (repo / "CLAUDE.md").unlink(); (repo / "CLAUDE.md").symlink_to(outside)
            self.assertFalse(report()["instructions"]["verified"])

    def test_forwarded_hook_target_drift_and_legacy_inventory_are_unmanaged(self):
        for change in ("bytes", "mode", "symlink", "legacy"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); repo = root / "repo"
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                original = repo / ".git/hooks/commit-msg"
                original.write_text("#!/bin/sh\nexit 0\n"); original.chmod(0o755)
                activation.initialize(PATH.parents[1] / "strict-mode", repo)
                managed = Path(subprocess.check_output(["git", "-C", str(repo), "config", "core.hooksPath"], text=True).strip())
                self.assertTrue(doctor.inspect(repo, runtime=PATH.parents[1])["project"]["managed"])
                wrapper = (managed / "commit-msg").read_bytes()
                if change == "bytes":
                    original.write_text("#!/bin/sh\nexit 7\n")
                elif change == "mode":
                    original.chmod(0o700)
                elif change == "symlink":
                    other = original.with_name("alternate")
                    other.write_bytes(original.read_bytes()); other.chmod(0o755)
                    original.unlink(); original.symlink_to(other.name)
                else:
                    metadata = managed / activation.ACTIVATION_FILE
                    record = json.loads(metadata.read_text())
                    record["schema"] = 1; record.pop("forwarded_targets", None)
                    metadata.write_text(json.dumps(record))
                report = doctor.inspect(repo, runtime=PATH.parents[1])
                self.assertFalse(report["project"]["managed"])
                self.assertFalse(report["hooks"]["chain"]["verified"])
                self.assertIn("hook_chain_mismatch", report["unresolved"])
                self.assertEqual((managed / "commit-msg").read_bytes(), wrapper)

    def test_real_activation_requires_intact_chain_metadata_and_original_hook(self):
        spec = importlib.util.spec_from_file_location("chain_initializer", PATH.parents[1] / "strict-mode/bin/strict_init.py")
        init = importlib.util.module_from_spec(spec); spec.loader.exec_module(init)
        for change in ("missing-chain", "changed-chain", "missing-metadata", "changed-original"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp).resolve() / "repo"; repo.mkdir()
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                original = repo / ".git/hooks/pre-commit"
                original.write_text("#!/bin/sh\nexit 0\n"); original.chmod(0o755)
                init.initialize(PATH.parents[1] / "strict-mode", repo)
                hookdir = Path(subprocess.check_output(["git", "-C", str(repo), "config", "core.hooksPath"], text=True).strip())
                self.assertTrue(doctor.inspect(repo, runtime=PATH.parents[1])["hooks"]["verified"])
                if change == "missing-chain":
                    (hookdir / ".caphe-chain.sh").unlink()
                elif change == "changed-chain":
                    (hookdir / ".caphe-chain.sh").write_text("CAPHE_PREVIOUS_HOOK=''\ntouch should-never-exist\n")
                elif change == "missing-metadata":
                    (hookdir / ".caphe-activation.json").unlink(missing_ok=True)
                else:
                    original.write_text("#!/bin/sh\nexit 7\n")
                before = {str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
                report = doctor.inspect(repo, runtime=PATH.parents[1])
                self.assertFalse(report["hooks"]["verified"])
                self.assertFalse(report["project"]["managed"])
                self.assertIn("hook_chain_mismatch", report["unresolved"])
                self.assertEqual({str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}, before)
