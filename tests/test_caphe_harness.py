import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import caphe_harness as harness


def sample_config(output_root):
    return {
        "schema_version": 1,
        "max_workers": 2,
        "output_root": str(output_root),
        "routes": [{
            "category": "lookup-extraction", "client": "codex", "model": "gpt-5.6-luna",
            "effort": "low", "context_budget_tokens": 1000, "permissions": "read-only",
            "timeout_seconds": 30, "max_output_bytes": 1024, "billing": "chatgpt", "enabled": True,
        }],
    }


class HarnessConfigTests(unittest.TestCase):
    def test_rejects_duplicate_or_ambiguous_route_fields(self):
        config = sample_config("/tmp/runs")
        config["routes"].append(dict(config["routes"][0]))
        with self.assertRaises(harness.HarnessError):
            harness.validate_config(config)
        config = sample_config("/tmp/runs")
        config["routes"][0]["model"] = ""
        with self.assertRaises(harness.HarnessError):
            harness.validate_config(config)

    def test_route_billing_cannot_claim_chatgpt_for_other_vendors(self):
        config = sample_config("/tmp/runs")
        config["routes"][0].update(client="claude", billing="chatgpt")
        with self.assertRaises(harness.HarnessError):
            harness.validate_config(config)
        config = sample_config("/tmp/runs")
        config["routes"][0].update(client="glm", model="glm-4.5", billing="provider-account")
        harness.validate_config(config)

    def test_codex_worker_command_pins_model_effort_profile_and_disables_children(self):
        route = sample_config("/tmp/runs")["routes"][0]
        argv = harness.build_command(route, Path("brief"), Path("result"), Path("repo"))
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--profile", argv)
        self.assertIn("caphe-worker", argv)
        self.assertIn("gpt-5.6-luna", argv)
        self.assertIn('model_reasoning_effort="low"', argv)
        self.assertIn("agents.max_depth=0", argv)
        self.assertNotIn("--sandbox", argv)

    def test_write_route_uses_explicit_profile_instead_of_legacy_sandbox(self):
        route = sample_config("/tmp/runs")["routes"][0]
        route["permissions"] = "worktree-write"
        argv = harness.build_command(route, Path("brief"), Path("result"), Path("repo"))
        self.assertNotIn("--sandbox", argv)
        self.assertNotIn("--worktree", argv)

    def test_write_profile_scopes_filesystem_writes_to_declared_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = sample_config(tmp)["routes"][0]
            route["permissions"] = "worktree-write"
            profile = harness._write_codex_profile(Path(tmp), route, ("src/one.py", "docs"))
            text = profile.read_text()
            self.assertIn('"." = "read"', text)
            self.assertIn('"src/one.py" = "write"', text)
            self.assertIn('"docs" = "write"', text)
            self.assertIn('network = { enabled = false }', text)
            self.assertTrue(harness._codex_profile_parse_check(route)["supported"])

    def test_brief_token_bound_is_conservative_and_deterministic(self):
        self.assertEqual(harness.estimate_tokens(""), 1)
        self.assertEqual(harness.estimate_tokens("abc"), 1)
        self.assertEqual(harness.estimate_tokens("abcd"), 2)
        with self.assertRaises(harness.HarnessError):
            harness.run_worker(sample_config("/tmp/runs"), sample_config("/tmp/runs")["routes"][0],
                               "/definitely/missing", "x" * 4000)

    def test_signed_update_apply_requires_the_previewed_exact_tag(self):
        with self.assertRaisesRegex(harness.HarnessError, "exact tag"):
            harness.update_runtime(apply=True)

    def test_batch_launches_only_enabled_routes_and_returns_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config(Path(tmp) / "runs")
            tasks = []
            for index in range(3):
                brief = Path(tmp) / f"brief-{index}.txt"
                brief.write_text(f"brief {index}")
                tasks.append({"category": "lookup-extraction", "repo": "/repo", "brief_file": str(brief)})
            with patch.object(harness, "run_worker", side_effect=lambda *a, **k: {"status": "planned"}) as launch:
                result = harness.run_batch(config, tasks)
            self.assertEqual(launch.call_count, 3)
            self.assertEqual(result["max_workers"], 2)
            self.assertEqual([task["status"] for task in result["tasks"]], ["planned"] * 3)
            self.assertEqual(launch.call_args.kwargs["parent_run_id"], result["batch_id"])
            config["routes"][0]["enabled"] = False
            with self.assertRaisesRegex(harness.HarnessError, "disabled"):
                harness.run_batch(config, tasks)


class HarnessEvidenceTests(unittest.TestCase):
    def test_codex_route_requires_unique_client_rollout_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions" / "2026" / "09" / "28"
            root.mkdir(parents=True)
            thread = "01234567-89ab-cdef-0123-456789abcdef"
            path = root / f"rollout-2026-09-28T00-00-00-{thread}.jsonl"
            path.write_text(json.dumps({"type": "turn_context", "payload": {
                "model": "gpt-5.6-luna", "effort": "low",
                "permission_profile": {"name": "caphe-worker"},
                "sandbox_policy": {"type": "restricted"}}}) + "\n")
            self.assertEqual(harness.codex_effective_route(thread, Path(tmp) / "sessions"),
                             {"model": "gpt-5.6-luna", "effort": "low", "cwd": None,
                              "permission_profile": {"name": "caphe-worker"},
                              "sandbox_policy": {"type": "restricted"}})
            (root / f"rollout-2026-09-28T00-01-00-{thread}.jsonl").write_text(path.read_text())
            self.assertIsNone(harness.codex_effective_route(thread, Path(tmp) / "sessions"))

    def test_codex_effort_nested_in_collaboration_mode_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            path = root / "2026" / "09" / "28"
            path.mkdir(parents=True)
            thread = "01234567-89ab-cdef-0123-456789abcdef"
            (path / f"rollout-2026-09-28T00-00-00-{thread}.jsonl").write_text(json.dumps({
                "type": "turn_context", "payload": {"model": "gpt-5.6-sol",
                    "collaboration_mode": {"settings": {"reasoning_effort": "medium"}}}}) + "\n")
            self.assertEqual(harness.codex_effective_route(thread, root),
                             {"model": "gpt-5.6-sol", "effort": "medium", "cwd": None,
                              "permission_profile": None, "sandbox_policy": None})

    def test_child_environment_excludes_all_provider_keys(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-openai", "ANTHROPIC_API_KEY": "secret-claude",
                                     "GOOGLE_API_KEY": "secret-google", "PATH": "/usr/bin"}, clear=True):
            env = harness._child_env("codex")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("GOOGLE_API_KEY", env)

    def test_doctor_reports_key_names_not_values_and_native_spawn_is_unused(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "harness.toml"
            config_path.write_bytes(harness.TEMPLATE.read_bytes())
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "do-not-print-this"}, clear=True), \
                 patch.object(harness, "_command_status", return_value={"installed": False, "version": None,
                                                                         "authenticated": False}):
                report = harness.doctor(config_path)
            encoded = json.dumps(report)
            self.assertIn("ANTHROPIC_API_KEY", encoded)
            self.assertNotIn("do-not-print-this", encoded)
            self.assertEqual(report["native_spawn"], "unused; workers are separate CLI processes")
            self.assertFalse(any(route["ready"] for route in report["routes"]))

    def test_dry_run_does_not_start_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c",
                            "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "init"], check=True)
            config = sample_config(Path(tmp) / "runs")
            route = config["routes"][0]
            with patch.object(harness, "_run_process", side_effect=AssertionError("worker must not start")):
                record = harness.run_worker(config, route, repo, "small brief", execute=False)
            self.assertEqual(record["status"], "planned")
            self.assertIn("explicit --execute", record["execution_blocker"])

    def test_restricted_codex_profile_is_parsed_without_model_dispatch(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as home_tmp, tempfile.TemporaryDirectory() as workspace_tmp:
            home = Path(home_tmp).resolve()
            route = sample_config(Path(workspace_tmp))["routes"][0]
            harness._write_codex_profile(home, route)
            run = subprocess.run(["codex", "--profile", "caphe-worker", "debug", "prompt-input", "profile check"],
                                 env={**os.environ, "CODEX_HOME": str(home)}, capture_output=True, text=True,
                                 timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_restricted_profile_denies_parent_auth_and_allows_only_listed_writes(self):
        with tempfile.TemporaryDirectory(prefix="caphe-test-", dir=Path.home()) as tmp:
            base = Path(tmp).resolve()
            workspace = base / "workspace"
            workspace.mkdir(mode=0o700)
            home = base / "codex-home"
            home.mkdir(mode=0o700)
            sandbox_tmp = base / "codex-tmp"
            sandbox_tmp.mkdir(mode=0o700)
            env = {**os.environ, "CODEX_HOME": str(home), "TMPDIR": str(sandbox_tmp)}
            secret = home / "auth.json"
            secret.write_text("CAPHE_SECRET_SENTINEL", encoding="utf-8")
            (home / "sessions").mkdir()
            (home / "sessions" / "parent-rollout.jsonl").write_text("CAPHE_PARENT_SENTINEL", encoding="utf-8")
            (workspace / "allowed.txt").write_text("before", encoding="utf-8")
            (workspace / "blocked.txt").write_text("before", encoding="utf-8")
            route = sample_config(workspace)["routes"][0]
            route["permissions"] = "worktree-write"
            harness._write_codex_profile(home, route, ("allowed.txt",))
            def sandbox(*command):
                return subprocess.run(["codex", "sandbox", "--profile", "caphe-worker",
                                       "--permission-profile", "caphe-worker", "--cd", str(workspace),
                                       *command], env=env, capture_output=True, text=True, timeout=15)
            for protected in (secret, home / "sessions" / "parent-rollout.jsonl"):
                read = sandbox("cat", str(protected))
                self.assertNotIn("CAPHE_SECRET_SENTINEL", read.stdout)
                self.assertNotIn("CAPHE_PARENT_SENTINEL", read.stdout)
                self.assertNotEqual(read.returncode, 0)
            write = sandbox("sh", "-c", "printf 'after' > allowed.txt; printf 'after' > blocked.txt")
            self.assertNotEqual(write.returncode, 0)
            self.assertEqual((workspace / "allowed.txt").read_text(), "after")
            self.assertEqual((workspace / "blocked.txt").read_text(), "before")


if __name__ == "__main__":
    unittest.main()
