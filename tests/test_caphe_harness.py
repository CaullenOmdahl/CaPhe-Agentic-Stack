import json
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
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


def init_repo(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=test", "-c",
                    "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "init"], check=True)
    return path


class HarnessConfigTests(unittest.TestCase):
    def test_signed_update_requires_executable_harness_entrypoint(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            stage = Path(tmp)
            command = stage / "bin" / "harness"
            command.parent.mkdir()
            command.write_text("#!/bin/sh\nexit 0\n")
            command.chmod(0o755)
            harness._require_harness_release_entrypoint(stage, {"payload": [["bin/harness", "0" * 64, 0o755]]})
            with self.assertRaisesRegex(harness.HarnessError, "executable bin/harness"):
                harness._require_harness_release_entrypoint(stage, {"payload": []})
            command.chmod(0o644)
            with self.assertRaisesRegex(harness.HarnessError, "executable bin/harness"):
                harness._require_harness_release_entrypoint(stage, {"payload": [["bin/harness", "0" * 64, 0o644]]})

    def test_systemd_scope_command_uses_control_group_cleanup(self):
        self.assertEqual(harness._systemd_scope_command(["codex", "exec"], "caphe-worker-test.scope"),
                         ["systemd-run", "--user", "--scope", "--wait", "--collect", "--quiet",
                          "--unit", "caphe-worker-test.scope", "--property=KillMode=control-group",
                          "--", "codex", "exec"])

    def test_systemd_containment_fails_closed_off_linux(self):
        with patch.object(harness.sys, "platform", "darwin"):
            status = harness._systemd_scope_status({})
        self.assertFalse(status["supported"])
        self.assertIn("Linux systemd", status["reason"])

    def test_route_membership_fields_must_be_strings(self):
        for field in ("client", "effort", "permissions", "billing"):
            config = sample_config("/tmp/runs")
            config["routes"][0][field] = ["malformed"]
            with self.subTest(field=field), self.assertRaisesRegex(harness.HarnessError, "fields must be strings"):
                harness.validate_config(config)

    def test_allowed_write_paths_cannot_include_git_metadata(self):
        with self.assertRaisesRegex(harness.HarnessError, "not normalized"):
            harness._allowed_write_paths(["."])
        for path in (".git", ".git/config", "src/.git/config"):
            with self.subTest(path=path), self.assertRaisesRegex(harness.HarnessError, "Git metadata"):
                harness._allowed_write_paths([path])

    def test_tar_validation_works_without_python_data_filter(self):
        payload = b"verified"
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:") as bundle:
            member = tarfile.TarInfo("nested/file.txt")
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
        archive.seek(0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(harness.tarfile.TarFile, "data_filter", None, create=True):
            with tarfile.open(fileobj=archive, mode="r:") as bundle:
                harness._extract_validated_tar(bundle, Path(tmp), "test")
            self.assertEqual((Path(tmp) / "nested/file.txt").read_bytes(), payload)

    def test_staged_installer_loader_uses_release_payload(self):
        source = Path(harness.__file__).resolve().parents[1] / "tools" / "stack_install.py"
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "tools" / "stack_install.py"
            staged.parent.mkdir()
            staged.write_bytes(source.read_bytes())
            module = harness._load_staged_installer(Path(tmp))
            self.assertEqual(Path(module.__file__), staged)

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

    def test_brief_token_bound_is_conservative_and_deterministic(self):
        self.assertEqual(harness.estimate_tokens(""), 1)
        self.assertEqual(harness.estimate_tokens("abc"), 1)
        self.assertEqual(harness.estimate_tokens("abcd"), 2)
        with self.assertRaises(harness.HarnessError):
            harness.run_worker(sample_config("/tmp/runs"), sample_config("/tmp/runs")["routes"][0],
                               "/definitely/missing", "x" * 4000)

    def test_signed_update_apply_requires_the_previewed_exact_tag(self):
        with self.assertRaisesRegex(harness.HarnessError, "exact previewed tag"):
            harness.update_runtime(apply=True)
        with self.assertRaisesRegex(harness.HarnessError, "reviewed preview"):
            harness.update_runtime(apply=True, tag="v1.2.3")

    def test_update_apply_requires_an_unchanged_saved_preview(self):
        report = {"status": "planned", "tag": "v1.2.3", "changes": {"added": ["bin/harness"]}}
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            digest = harness._write_update_preview(state, report)
            harness._check_update_preview(state, digest, report)
            with self.assertRaisesRegex(harness.HarnessError, "changed since preview"):
                harness._check_update_preview(state, digest, {**report, "tag": "v1.2.4"})

    def test_release_lookup_reports_non_not_found_http_errors(self):
        error = harness.urllib.error.HTTPError("https://github.invalid/release", 503, "unavailable", {}, None)
        with patch.object(harness.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(harness.HarnessError, "release lookup failed"):
                harness._release_from_url("https://github.invalid/release")
        error.close()

    def test_subdirectory_worker_cannot_place_output_in_repository_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            nested = root / "src"
            nested.mkdir()
            with self.assertRaisesRegex(harness.HarnessError, "separate from the source repository"):
                harness._safe_output_dir(root / "runs", nested)

    def test_output_root_rejects_symlinked_parent_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            external = root.parent / (root.name + "-external")
            external.mkdir()
            alias = root / "alias"
            alias.symlink_to(external, target_is_directory=True)
            try:
                with self.assertRaisesRegex(harness.HarnessError, "symlinks"):
                    harness._safe_output_dir(alias / "runs", root)
            finally:
                alias.unlink()
                external.rmdir()

    def test_write_scope_sees_ordinary_and_ignored_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            (root / ".gitignore").write_text("ignored.out\n")
            subprocess.run(["git", "-C", str(root), "add", ".gitignore"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "init"], check=True)
            (root / "ordinary.out").write_text("out of scope")
            (root / "ignored.out").write_text("out of scope")
            nested_file = "src/new_dir/output.txt"
            (root / nested_file).parent.mkdir(parents=True)
            (root / nested_file).write_text("declared output")
            changed = set(harness._worktree_changes(root))
            self.assertEqual(changed, {"ignored.out", "ordinary.out", nested_file})
            self.assertTrue(harness._changes_allowed([nested_file], [nested_file]))

    def test_worktree_timeout_is_recorded_as_unverifiable(self):
        with patch.object(harness.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 20)):
            self.assertIsNone(harness._worktree_changes("/repo"))

    def test_snapshot_baseline_detects_changes_even_after_worker_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            output = root / "output.txt"
            output.write_text("initial")
            subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "baseline"], check=True)
            baseline = harness._tree_manifest(root)
            output.write_text("unauthorized but committed")
            subprocess.run(["git", "-C", str(root), "add", "output.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "worker commit"], check=True)
            self.assertEqual(harness._worktree_changes(root, baseline), ["output.txt"])

    def test_snapshot_manifest_allows_only_required_new_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            baseline = {}
            (root / "reports").mkdir()
            (root / "reports/output.md").write_text("declared")
            self.assertEqual(harness._worktree_changes(root, baseline, ["reports/output.md"]),
                             ["reports/output.md"])

    def test_file_allowlist_does_not_authorize_descendants(self):
        baseline = {"src/config.py": ("file", 0o644, "baseline-hash")}
        self.assertFalse(harness._changes_allowed(
            ["src/config.py", "src/config.py/undeclared"], ["src/config.py"], baseline))
        directory_baseline = {"docs": ("directory", 0o755, None)}
        self.assertTrue(harness._changes_allowed(["docs/new.md"], ["docs"], directory_baseline))

    def test_tree_manifest_rejects_oversized_sparse_outputs_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            sparse = Path(tmp) / "sparse.out"
            with sparse.open("wb") as stream:
                stream.truncate(64 * 1024 * 1024)
            self.assertIsNone(harness._tree_manifest(tmp, max_bytes=1024))

    def test_bounded_result_truncates_sparse_file_without_full_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.txt"
            with result.open("wb") as stream:
                stream.write(b"head")
                stream.truncate(64 * 1024 * 1024)
            data, truncated = harness._bounded_result(result, 1024)
            self.assertTrue(truncated)
            self.assertEqual(len(data), 1024)
            self.assertEqual(result.stat().st_size, 1024)

    def test_release_staging_force_adds_ignored_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
            (source / ".gitignore").write_text("ignored.txt\n")
            (source / "ignored.txt").write_text("signed tracked payload")
            env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                   "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
            harness._stage_release_files(source, Path(tmp), env)
            tracked = subprocess.run(["git", "-C", str(source), "ls-files", "-z"],
                                     capture_output=True, check=True).stdout.split(b"\0")
            self.assertIn(b"ignored.txt", tracked)

    def test_snapshot_uses_captured_revision_after_head_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            source = repo / "value.txt"
            source.write_text("captured")
            subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
            commit_args = ["git", "-C", str(repo), "-c", "user.name=test", "-c",
                           "user.email=test@example.invalid", "commit", "-qm"]
            subprocess.run([*commit_args, "first"], check=True)
            captured = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                      capture_output=True, text=True, check=True).stdout.strip()
            source.write_text("later")
            subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)
            subprocess.run([*commit_args, "second"], check=True)
            snapshot = harness._snapshot_repo(repo, Path(tmp) / "snapshot", captured)
            self.assertEqual((snapshot / "value.txt").read_text(), "captured")

    def test_snapshot_indexes_force_added_ignored_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            (repo / ".gitignore").write_text("ignored.txt\n")
            (repo / "ignored.txt").write_text("tracked by force")
            subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "-f", "ignored.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "init"], check=True)
            snapshot = harness._snapshot_repo(repo, Path(tmp) / "snapshot")
            tracked = subprocess.run(["git", "-C", str(snapshot), "ls-files", "-z"],
                                     capture_output=True, check=True).stdout.split(b"\0")
            self.assertIn(b"ignored.txt", tracked)
            self.assertEqual(harness._worktree_changes(snapshot), [])

    def test_route_verification_requires_expected_cwd_for_every_permission(self):
        route = sample_config("/tmp/runs")["routes"][0]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            elsewhere = Path(tmp) / "elsewhere"
            workspace.mkdir()
            elsewhere.mkdir()
            effective = {"model": route["model"], "effort": route["effort"], "cwd": str(elsewhere),
                         "permission_profile": {"name": "caphe-worker"},
                         "sandbox_policy": {"type": "restricted"}}
            self.assertFalse(harness._effective_route_verified(route, effective, workspace))
            effective["cwd"] = str(workspace)
            self.assertTrue(harness._effective_route_verified(route, effective, workspace))

    def test_batch_launches_only_enabled_routes_and_returns_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config(Path(tmp) / "runs")
            repo = init_repo(Path(tmp) / "repo")
            tasks = []
            for index in range(3):
                brief = Path(tmp) / f"brief-{index}.txt"
                brief.write_text(f"brief {index}")
                tasks.append({"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief)})
            with patch.object(harness, "run_worker", side_effect=lambda *a, **k: {"status": "planned"}) as launch:
                result = harness.run_batch(config, tasks)
            self.assertEqual(launch.call_count, 3)
            self.assertEqual(result["max_workers"], 2)
            self.assertEqual([task["status"] for task in result["tasks"]], ["planned"] * 3)
            self.assertEqual(launch.call_args.kwargs["parent_run_id"], result["batch_id"])
            config["routes"][0]["enabled"] = False
            with self.assertRaisesRegex(harness.HarnessError, "disabled"):
                harness.run_batch(config, tasks)

    def test_batch_rejects_missing_write_allowlist_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config(Path(tmp) / "runs")
            config["routes"][0]["permissions"] = "worktree-write"
            repo = init_repo(Path(tmp) / "repo")
            brief = Path(tmp) / "brief.md"
            brief.write_text("brief")
            tasks = [
                {"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief),
                 "allow_write": ["result.md"]},
                {"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief)},
            ]
            with patch.object(harness, "run_worker") as launch:
                with self.assertRaisesRegex(harness.HarnessError, "explicit allow_write"):
                    harness.run_batch(config, tasks, execute=True)
            launch.assert_not_called()

    def test_batch_rejects_malformed_retry_id_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config(Path(tmp) / "runs")
            repo = init_repo(Path(tmp) / "repo")
            brief = Path(tmp) / "brief.md"
            brief.write_text("brief")
            tasks = [
                {"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief)},
                {"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief),
                 "retry_of": "bad id"},
            ]
            with patch.object(harness, "run_worker") as launch:
                with self.assertRaisesRegex(harness.HarnessError, "retry_of"):
                    harness.run_batch(config, tasks, execute=True)
            launch.assert_not_called()

    def test_batch_rejects_invalid_repository_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sample_config(Path(tmp) / "runs")
            repo = init_repo(Path(tmp) / "repo")
            non_git = Path(tmp) / "not-git"
            non_git.mkdir()
            brief = Path(tmp) / "brief.md"
            brief.write_text("brief")
            for invalid in (str(Path(tmp) / "missing"), str(non_git)):
                tasks = [
                    {"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief)},
                    {"category": "lookup-extraction", "repo": invalid, "brief_file": str(brief)},
                ]
                with self.subTest(repo=invalid), patch.object(harness, "run_worker") as launch:
                    with self.assertRaises(harness.HarnessError):
                        harness.run_batch(config, tasks, execute=True)
                    launch.assert_not_called()

    def test_batch_rejects_unhashable_category_before_route_lookup(self):
        with patch.object(harness, "run_worker") as launch:
            with self.assertRaisesRegex(harness.HarnessError, "category must be a string"):
                harness.run_batch(sample_config("/tmp/runs"), [
                    {"category": ["lookup-extraction"], "repo": "/repo", "brief_file": "/brief"}
                ], execute=True)
        launch.assert_not_called()


class HarnessEvidenceTests(unittest.TestCase):
    def test_worker_preflight_rejects_missing_os_containment_before_dispatch(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            repo = init_repo(Path(tmp) / "repo")
            config = sample_config(Path(tmp) / "runs")
            with patch.object(harness, "_command_status", return_value={"installed": True,
                           "authenticated": True, "auth_mode": "chatgpt"}), \
                 patch.object(harness, "_systemd_scope_status", return_value={"supported": False,
                       "reason": "test containment unavailable"}), \
                 patch.object(harness, "_run_process", side_effect=AssertionError("worker must not start")):
                record = harness.run_worker(config, config["routes"][0], repo, "small brief", execute=True)
            self.assertEqual(record["status"], "preflight_failed")
            self.assertIn("test containment unavailable", record["execution_error"])

    @unittest.skipUnless(os.name == "posix", "isolated process groups require POSIX")
    def test_process_group_descendants_are_stopped_before_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "late-write"
            child = ("import pathlib,time; time.sleep(0.5); pathlib.Path(" + repr(str(marker))
                     + ").write_text('escaped')")
            parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child) + "])"
            started = harness.time.monotonic()
            result = harness._run_process([sys.executable, "-c", parent], cwd=tmp, env=os.environ,
                                          prompt="", timeout=3)
            self.assertEqual(result[0], 0)
            self.assertLess(harness.time.monotonic() - started, 3)
            harness.time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_failed_worker_status_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "harness.toml"
            config_path.write_text('schema_version = 1\nmax_workers = 1\noutput_root = ' +
                                   json.dumps(tmp + '/runs') + '\n'
                                   '[[routes]]\ncategory = "lookup-extraction"\nclient = "codex"\n'
                                   'model = "gpt-5.6-luna"\neffort = "low"\ncontext_budget_tokens = 1000\n'
                                   'permissions = "read-only"\ntimeout_seconds = 30\nmax_output_bytes = 1024\n'
                                   'billing = "chatgpt"\nenabled = true\n')
            brief = Path(tmp) / "brief.md"
            brief.write_text("brief")
            with patch.object(harness, "run_worker", return_value={"status": "unverified"}), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = harness.main(["worker", "--config", str(config_path), "--category",
                                       "lookup-extraction", "--brief-file", str(brief)])
            self.assertEqual(result, 1)

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
            self.assertIn("process_containment", report)
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

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
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
            output_path = base / "worker-result.txt"
            harness._write_codex_profile(home, route, ("allowed.txt",), output_path=output_path)
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
            result_write = sandbox("sh", "-c", "printf 'result' > " + str(output_path))
            self.assertEqual(result_write.returncode, 0, result_write.stderr)
            self.assertEqual(output_path.read_text(), "result")


if __name__ == "__main__":
    unittest.main()
