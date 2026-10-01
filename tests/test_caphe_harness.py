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
import copy
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


class WorkerPermissionTests(unittest.TestCase):
    def test_mount_scaffolding_is_baselined_but_never_writable_output(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(harness.sys, "platform", "linux"):
            root = Path(tmp)
            workspace = root / "workspace"
            (workspace / "allowed").mkdir(parents=True)
            result = root / "result"
            result.mkdir()
            mounts = harness._prepare_sandbox_mounts([workspace / "allowed", result])
            baseline = harness._tree_manifest(workspace)
            self.assertEqual(len(mounts), 6)
            self.assertTrue(harness._sandbox_mounts_unchanged(mounts))
            self.assertTrue(harness._result_dir_clean(result, result / "out", mounts))
            (workspace / "allowed" / "marker").write_text("ok")
            self.assertEqual(harness._worktree_changes(workspace, baseline), ["allowed/marker"])
            (workspace / "allowed" / ".codex" / "injected").write_text("bad")
            self.assertFalse(harness._sandbox_mounts_unchanged(mounts))
            (result / ".agents" / "injected").write_text("bad")
            self.assertFalse(harness._result_dir_clean(result, result / "out", mounts))

    def test_mount_scaffolding_does_not_exempt_existing_or_replaced_paths(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(harness.sys, "platform", "linux"):
            root = Path(tmp)
            (root / ".codex").mkdir()
            (root / ".codex" / "tracked").write_text("keep")
            mounts = harness._prepare_sandbox_mounts([root])
            self.assertNotIn(str(root / ".codex"), mounts)
            self.assertEqual((root / ".codex" / "tracked").read_text(), "keep")
            (root / ".agents").rmdir()
            (root / ".agents").symlink_to(root / ".codex", target_is_directory=True)
            self.assertFalse(harness._sandbox_mounts_unchanged(mounts))

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_real_exec_uses_explicit_permissions_without_a_model_request(self):
        with tempfile.TemporaryDirectory(prefix="caphe-exec-test-", dir=Path.home()) as tmp:
            base = Path(tmp).resolve()
            home = base / "home"
            home.mkdir()
            workspace = init_repo(base / "workspace")
            (workspace / "allowed").mkdir()
            (base / "result").mkdir()
            route = dict(sample_config(tmp)["routes"][0], permissions="worktree-write", model="offline")
            profile = harness._write_codex_profile(home, route, ("allowed",), output_path=base / "result/out")
            argv = harness.build_command(route, base / "brief", base / "result/out", workspace, profile_path=profile)
            argv[-1:-1] = ["--config", 'model_provider="caphe-offline"', "--config",
                          'model_providers.caphe-offline={name="Offline probe",base_url="http://127.0.0.1:9",'
                          'wire_api="responses",request_max_retries=0,stream_max_retries=0}']
            env = {**harness._child_env("codex"), "CODEX_HOME": str(home)}
            result = harness._run_process(argv, cwd=workspace, env=env, prompt="Reply OK", timeout=5)
            events = harness._json_records(result[1].decode())
            started = next((event for event in events if event.get("type") == "thread.started"), None)
            self.assertIsNotNone(started, result[2].decode())
            evidence = harness.codex_session_evidence(started["thread_id"], home / "sessions")
            self.assertTrue(evidence and evidence["routes"])
            expected = harness._expected_permission_profile(profile, workspace)
            self.assertTrue(all(harness._effective_route_verified(route, context, workspace, expected, home)
                                for context in evidence["routes"]), evidence)

    def test_probe_requires_real_output_and_exact_write_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / "probe-output").mkdir(parents=True)
            output = Path(tmp) / "result.txt"
            output.write_text("marker\n")
            outcome = {"status": "completed", "route_verified": True, "write_scope_verified": True,
                       "result_path": str(output), "worktree": str(workspace)}
            route = sample_config(tmp)["routes"][0]
            self.assertTrue(harness._probe_behavior_verified(outcome, route, "marker"))
            route["permissions"] = "worktree-write"
            self.assertFalse(harness._probe_behavior_verified(outcome, route, "marker"))
            marker = workspace / "probe-output/marker.txt"
            marker.write_text("incorrect")
            self.assertFalse(harness._probe_behavior_verified(outcome, route, "marker"))
            marker.write_text("marker\n")
            self.assertTrue(harness._probe_behavior_verified(outcome, route, "marker"))
            outcome["route_verified"] = False
            self.assertFalse(harness._probe_behavior_verified(outcome, route, "marker"))

    def test_session_evidence_preserves_every_turn_including_invalid_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            thread = "01234567-89ab-cdef-0123-456789abcdef"
            path = Path(tmp) / f"rollout-2026-10-01T00-00-00-{thread}.jsonl"
            contexts = [{"model": "gpt-5.6-luna", "effort": "low", "active_permission_profile": {"id": ":read-only"}},
                        {}, {"model": "gpt-5.6-luna", "effort": "low", "active_permission_profile": {"id": "caphe-worker"}}]
            path.write_text("".join(json.dumps({"type": "turn_context", "payload": context}) + "\n" for context in contexts))
            evidence = harness.codex_session_evidence(thread, tmp)
            self.assertEqual(len(evidence["routes"]), 3)
            self.assertEqual(evidence["routes"][0]["active_permission_profile"]["id"], ":read-only")
            self.assertIsNone(evidence["routes"][1])
            self.assertEqual(evidence["routes"][2]["active_permission_profile"]["id"], "caphe-worker")

    def test_empty_committed_tree_can_be_snapshotted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "repo")
            snapshot = harness._snapshot_repo(repo, Path(tmp) / "snapshot")
            self.assertEqual(harness._worktree_changes(snapshot), [])

    def test_exec_receives_permissions_even_when_user_config_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = sample_config(tmp)["routes"][0]
            route["permissions"] = "worktree-write"
            profile = harness._write_codex_profile(Path(tmp), route, ("allowed",))
            argv = harness.build_command(route, Path("brief"), Path("result"), Path("repo"),
                                         profile_path=profile)
            overrides = [argv[index + 1] for index, value in enumerate(argv) if value == "--config"]
            self.assertIn('default_permissions="caphe-worker"', overrides)
            self.assertTrue(any(value.startswith("permissions.caphe-worker.filesystem=")
                                and '"allowed" = "write"' in value for value in overrides))
            self.assertIn('permissions.caphe-worker.network={ "enabled" = false }', overrides)

    def test_effective_permissions_must_match_expected_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            home = Path(tmp) / "home"
            home.mkdir()
            route = dict(sample_config(tmp)["routes"][0], permissions="worktree-write")
            result = Path(tmp) / "result" / "out.txt"
            profile = harness._write_codex_profile(home, route, ("allowed",), output_path=result)
            expected = harness._expected_permission_profile(profile, workspace)
            effective = {"model": route["model"], "effort": route["effort"], "cwd": str(workspace),
                         "active_permission_profile": {"id": "caphe-worker"},
                         "permission_profile": copy.deepcopy(expected),
                         "sandbox_policy": {"type": "workspace-write", "network_access": False,
                                            "exclude_tmpdir_env_var": True, "exclude_slash_tmp": True,
                                            "writable_roots": [str(workspace / "allowed"), str(result.parent)]}}
            self.assertTrue(harness._effective_route_verified(route, effective, workspace, expected, home))
            mutations = [
                ("readonly", lambda value: value.update(sandbox_policy={"type": "read-only"})),
                ("active", lambda value: value.update(active_permission_profile={"id": ":read-only"})),
                ("network", lambda value: value["permission_profile"].update(network="enabled")),
                ("network_missing", lambda value: value["permission_profile"].pop("network")),
                ("grants_missing", lambda value: value["permission_profile"].update(file_system={"type": "restricted", "entries": []})),
                ("broad_read", lambda value: value["permission_profile"]["file_system"]["entries"].append(
                    {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"})),
                ("broad_write", lambda value: value["sandbox_policy"]["writable_roots"].append(str(workspace))),
                ("tmp_write", lambda value: value["sandbox_policy"].update(exclude_slash_tmp=False)),
                ("wrong_cwd", lambda value: value.update(cwd=str(home))),
                ("missing_deny", lambda value: value["permission_profile"]["file_system"]["entries"].remove(
                    next(entry for entry in value["permission_profile"]["file_system"]["entries"] if entry["access"] == "deny"))),
            ]
            for name, mutate in mutations:
                changed = copy.deepcopy(effective)
                mutate(changed)
                with self.subTest(name=name):
                    self.assertFalse(harness._effective_route_verified(route, changed, workspace, expected, home))
            legacy = copy.deepcopy(effective)
            legacy.pop("active_permission_profile")
            legacy["permission_profile"]["name"] = "caphe-worker"
            self.assertTrue(harness._effective_route_verified(route, legacy, workspace, expected, home))
            legacy["permission_profile"] = {"name": "caphe-worker"}
            self.assertFalse(harness._effective_route_verified(route, legacy, workspace, expected, home))
            helper = {"path": {"type": "path", "path": str(home / "tmp/arg0/codex-arg0ABC123")}, "access": "read"}
            effective["permission_profile"]["file_system"]["entries"].append(helper)
            self.assertTrue(harness._effective_route_verified(route, effective, workspace, expected, home))
            helper["access"] = "write"
            self.assertFalse(harness._effective_route_verified(route, effective, workspace, expected, home))


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
                         ["systemd-run", "--user", "--scope", "--collect", "--quiet",
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
        with tempfile.TemporaryDirectory() as tmp:
            profile = harness._write_codex_profile(Path(tmp), route)
            argv = harness.build_command(route, Path("brief"), Path("result"), Path("repo"), profile_path=profile)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn('default_permissions="caphe-worker"', argv)
        self.assertIn("gpt-5.6-luna", argv)
        self.assertIn('model_reasoning_effort="low"', argv)
        self.assertIn("agents.max_depth=0", argv)
        self.assertNotIn("--sandbox", argv)

    def test_write_route_uses_explicit_profile_instead_of_legacy_sandbox(self):
        route = sample_config("/tmp/runs")["routes"][0]
        route["permissions"] = "worktree-write"
        with tempfile.TemporaryDirectory() as tmp:
            profile = harness._write_codex_profile(Path(tmp), route)
            argv = harness.build_command(route, Path("brief"), Path("result"), Path("repo"), profile_path=profile)
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
        self.assertEqual(harness.estimate_tokens("abc"), 3)  # one token per UTF-8 byte upper bound
        self.assertEqual(harness.estimate_tokens("é"), 2)
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
            self.assertFalse(harness._effective_route_verified(route, effective, workspace))

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
            (repo / "out").mkdir()  # a directory grant, valid on every platform
            (repo / "out" / ".keep").write_text("")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
                            "commit", "-qm", "out"], check=True)
            brief = Path(tmp) / "brief.md"
            brief.write_text("brief")
            tasks = [
                {"category": "lookup-extraction", "repo": str(repo), "brief_file": str(brief),
                 "allow_write": ["out"]},
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
                              "active_permission_profile": None,
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
                              "permission_profile": None, "active_permission_profile": None, "sandbox_policy": None})

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
            # Directory grant: Codex's Linux sandbox panics on file grants (see
            # _validate_platform_write_grants); directories work on every platform.
            (workspace / "allowed").mkdir()
            (workspace / "allowed" / "out.txt").write_text("before", encoding="utf-8")
            (workspace / "blocked.txt").write_text("before", encoding="utf-8")
            route = sample_config(workspace)["routes"][0]
            route["permissions"] = "worktree-write"
            (base / "result").mkdir(mode=0o700)
            output_path = base / "result" / "worker-result.txt"
            harness._write_codex_profile(home, route, ("allowed",), output_path=output_path)
            def sandbox(*command):
                return subprocess.run(["codex", "sandbox", "--profile", "caphe-worker",
                                       "--permission-profile", "caphe-worker", "--cd", str(workspace),
                                       *command], env=env, capture_output=True, text=True, timeout=15)
            for protected in (secret, home / "sessions" / "parent-rollout.jsonl"):
                read = sandbox("cat", str(protected))
                self.assertNotIn("CAPHE_SECRET_SENTINEL", read.stdout)
                self.assertNotIn("CAPHE_PARENT_SENTINEL", read.stdout)
                self.assertNotEqual(read.returncode, 0)
            write = sandbox("sh", "-c", "printf 'after' > allowed/out.txt; printf 'after' > blocked.txt")
            self.assertNotEqual(write.returncode, 0)
            self.assertEqual((workspace / "allowed" / "out.txt").read_text(), "after")
            self.assertEqual((workspace / "blocked.txt").read_text(), "before")
            result_write = sandbox("sh", "-c", "printf 'result' > " + str(output_path))
            self.assertEqual(result_write.returncode, 0, result_write.stderr)
            self.assertEqual(output_path.read_text(), "result")


class ReviewFindingTests(unittest.TestCase):
    """Regression tests for PR #15 review findings that remained open on its final head."""

    def test_scope_query_failure_is_unknown_not_stopped(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="bus unavailable")
        with patch.object(harness.subprocess, "run", return_value=failed):
            self.assertIsNone(harness._systemd_scope_state("caphe-worker-x.scope", {}))
            self.assertFalse(harness._stop_systemd_scope("caphe-worker-x.scope", {}))
        gone = subprocess.CompletedProcess([], 0, stdout="inactive\n", stderr="")
        with patch.object(harness.subprocess, "run", return_value=gone):
            self.assertIs(harness._systemd_scope_state("caphe-worker-x.scope", {}), False)
            self.assertTrue(harness._stop_systemd_scope("caphe-worker-x.scope", {}))

    def test_token_estimate_never_undercounts_one_token_per_byte(self):
        dense = "\x7f" * 2999 + "é"  # high-entropy text can approach one token per byte
        self.assertGreaterEqual(harness.estimate_tokens(dense), len(dense.encode("utf-8")))
        self.assertEqual(harness.brief_byte_limit({"context_budget_tokens": 1000}), 1000)

    def test_snapshot_keeps_internal_symlinks_and_rejects_escaping_ones(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            repo = init_repo(Path(tmp) / "repo")
            (repo / "docs").mkdir()
            (repo / "docs" / "guide.md").write_text("guide")
            os.symlink("docs/guide.md", repo / "link.md")
            os.symlink("../guide.md", repo / "docs" / "self.md")  # stays inside after normalisation
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
                            "commit", "-qm", "links"], check=True)
            snap = harness._snapshot_repo(repo, Path(tmp) / "snap")
            self.assertEqual(os.readlink(snap / "link.md"), "docs/guide.md")
            self.assertEqual((snap / "link.md").read_text(), "guide")
            for target in ("../outside", "/etc/passwd", "docs/../../outside"):
                bad = init_repo(Path(tmp) / ("bad" + str(abs(hash(target)))))
                os.symlink(target, bad / "escape")
                subprocess.run(["git", "-C", str(bad), "add", "."], check=True)
                subprocess.run(["git", "-C", str(bad), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
                                "commit", "-qm", "escape"], check=True)
                with self.assertRaises(harness.HarnessError):
                    harness._snapshot_repo(bad, Path(tmp) / ("snap-" + bad.name))

    def test_read_only_runs_are_verified_against_the_snapshot_baseline(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            workspace = init_repo(Path(tmp) / "ws")
            (workspace / "a.txt").write_text("before")
            baseline = harness._tree_manifest(workspace)
            route = {"permissions": "read-only"}
            ok = harness._verify_write_scope(route, str(workspace), workspace, baseline, ())
            self.assertTrue(ok["write_scope_verified"])
            (workspace / "a.txt").write_text("after")
            changed = harness._verify_write_scope(route, str(workspace), workspace, baseline, ())
            self.assertFalse(changed["write_scope_verified"])
            self.assertEqual(changed["changed_paths"], ["a.txt"])
            self.assertFalse(harness._verify_write_scope(route, None, workspace, baseline, ())["write_scope_verified"])

    def test_execution_requires_a_passing_live_profile_self_test(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            repo = init_repo(Path(tmp) / "repo")
            config = sample_config(Path(tmp) / "runs")
            with patch.object(harness, "_command_status", return_value={"installed": True,
                           "authenticated": True, "auth_mode": "chatgpt"}), \
                 patch.object(harness, "_systemd_scope_status", return_value={"supported": True}), \
                 patch.object(harness, "_codex_profile_parse_check", return_value={"supported": False,
                       "reason": "filesystem profile allows an undeclared write"}), \
                 patch.object(harness, "_run_process", side_effect=AssertionError("worker must not start")):
                record = harness.run_worker(config, config["routes"][0], repo, "small brief", execute=True)
            self.assertEqual(record["status"], "preflight_failed")
            self.assertIn("undeclared write", record["execution_error"])

    def test_installed_runtime_may_update_itself_but_a_source_checkout_may_not(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            installed = Path(tmp) / "runtime"
            installed.mkdir()
            (installed / ".caphe-runtime.json").write_text("{}")
            self.assertEqual(harness._update_target(installed, str(installed)), installed)
            checkout = init_repo(Path(tmp) / "checkout")
            (checkout / ".caphe-runtime.json").write_text("{}")
            with self.assertRaisesRegex(harness.HarnessError, "source checkout"):
                harness._update_target(checkout, str(checkout))
            self.assertEqual(harness._update_target(checkout, str(installed)), installed)
            with self.assertRaisesRegex(harness.HarnessError, "inventoried"):
                harness._update_target(checkout, str(Path(tmp) / "missing"))

    def test_profile_lets_the_sandbox_read_codexs_own_install_but_nothing_broader(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            pkg = Path(tmp) / "node_modules" / "@openai" / "codex"
            (pkg / "bin").mkdir(parents=True)
            (pkg / "bin" / "codex.js").write_text("")
            route = dict(sample_config(tmp)["routes"][0])
            home = Path(tmp) / "codex-home"
            home.mkdir()
            with patch.object(harness.shutil, "which", return_value=str(pkg / "bin" / "codex.js")):
                text = harness._write_codex_profile(home, route).read_text()
            self.assertIn(json.dumps(str(pkg.resolve())) + ' = "read"', text)
            for broad in (Path.home(), Path("/")):
                self.assertIsNone(harness._codex_install_root(str(broad / "codex")))

    @unittest.skipUnless(harness._systemd_scope_status(dict(os.environ)).get("supported"),
                         "needs a Linux user systemd manager")
    def test_real_systemd_scope_stops_setsid_descendants_before_return(self):
        # Real-artifact check for the containment boundary: a worker that detaches a grandchild
        # with setsid() escapes its process group, but not its systemd scope.
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "escaped-write"
            grandchild = ("import os,pathlib,time; os.setsid(); time.sleep(1.5); pathlib.Path("
                          + repr(str(marker)) + ").write_text('escaped')")
            # The grandchild calls setsid() itself; it must not already lead a session.
            # The worker waits until the grandchild has left its process group, then exits.
            worker = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(grandchild)
                      + "], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(0.6)")
            unit = "caphe-worker-test-" + os.urandom(4).hex() + ".scope"
            env = dict(os.environ)
            result = harness._run_process([sys.executable, "-c", worker], cwd=tmp, env=env, prompt="",
                                          timeout=20, containment_unit=unit)
            self.assertEqual(result[0], 0, result[2])
            self.assertIs(harness._systemd_scope_state(unit, env), False)
            harness.time.sleep(2.5)
            self.assertFalse(marker.exists(), "a setsid descendant outlived the worker scope")

    def test_effective_route_rejects_any_recorded_network_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = sample_config(tmp)["routes"][0]
            base = {"model": route["model"], "effort": route["effort"], "cwd": tmp,
                    "permission_profile": {"name": "caphe-worker"}}
            ok = dict(base, sandbox_policy={"type": "workspace-write"})
            self.assertFalse(harness._effective_route_verified(route, ok, tmp))
            for policy in ({"type": "workspace-write", "network_access": True},
                           {"type": "managed", "network": {"enabled": True}},
                           {"type": "workspace-write", "network": True}):
                self.assertFalse(harness._effective_route_verified(route, dict(base, sandbox_policy=policy), tmp))
            profile = dict(base, sandbox_policy={"type": "workspace-write"},
                           permission_profile={"name": "caphe-worker", "network": {"enabled": True}})
            self.assertFalse(harness._effective_route_verified(route, profile, tmp))

    def test_completed_run_without_a_result_file_is_not_completed(self):
        record = {"status": "completed", "result_path": None}
        self.assertEqual(harness._require_result(record)["status"], "failed_no_result")
        kept = {"status": "timed_out", "result_path": None}
        self.assertEqual(harness._require_result(kept)["status"], "timed_out")

    def test_sandbox_grants_are_directories_on_linux_while_verification_stays_exact(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            ws = Path(tmp)
            (ws / "src").mkdir()
            (ws / "src" / "a.py").write_text("x")
            (ws / "top.txt").write_text("x")
            grants = harness._sandbox_write_grants(ws, ("src/a.py", "src", "top.txt", "new/deep/file.md"),
                                                   platform="linux")
            self.assertEqual(grants, [".", "src"])  # nearest existing directories, deduplicated
            self.assertEqual(harness._sandbox_write_grants(ws, ("src/a.py",), platform="darwin"), ["src/a.py"])
            baseline = harness._tree_manifest(ws)
            (ws / "src" / "b.py").write_text("sibling")
            changed = harness._worktree_changes(ws, baseline, ("src/a.py",))
            self.assertFalse(harness._changes_allowed(changed, ("src/a.py",), baseline))

    def test_install_root_grant_is_exact_package_or_binary_folder(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            pkg = Path(tmp) / "lib" / "node_modules" / "@openai" / "codex"
            (pkg / "bin").mkdir(parents=True)
            (pkg / "bin" / "codex.js").write_text("")
            self.assertEqual(harness._codex_install_root(str(pkg / "bin" / "codex.js")), pkg.resolve())
            native = Path(tmp) / "dot-local" / "bin"
            native.mkdir(parents=True)
            (native / "codex").write_text("")
            self.assertEqual(harness._codex_install_root(str(native / "codex")), native.resolve())

    def test_result_directory_must_hold_only_the_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_dir = Path(tmp)
            (result_dir / "result.txt").write_text("ok")
            self.assertTrue(harness._result_dir_clean(result_dir, result_dir / "result.txt"))
            (result_dir / "filler.bin").write_bytes(b"0" * 10)
            self.assertFalse(harness._result_dir_clean(result_dir, result_dir / "result.txt"))
            self.assertFalse((result_dir / "filler.bin").exists())
            self.assertTrue((result_dir / "result.txt").exists())
            (result_dir / "result.txt").unlink()
            (result_dir / "result.txt").mkdir()  # a worker swapped the result for a directory
            (result_dir / "result.txt" / "big").write_bytes(b"0")
            self.assertFalse(harness._result_dir_clean(result_dir, result_dir / "result.txt"))
            self.assertFalse((result_dir / "result.txt").exists())
            os.symlink("/etc/passwd", result_dir / "result.txt")
            self.assertFalse(harness._result_dir_clean(result_dir, result_dir / "result.txt"))
            self.assertFalse((result_dir / "result.txt").is_symlink())

    def test_archive_entries_through_an_earlier_symlink_are_rejected(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as bundle:
            link = tarfile.TarInfo("dir"); link.type = tarfile.SYMTYPE; link.linkname = "."
            bundle.addfile(link)
            escape = tarfile.TarInfo("dir/escape"); escape.type = tarfile.SYMTYPE; escape.linkname = ".."
            bundle.addfile(escape)
        buffer.seek(0)
        with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=buffer, mode="r:") as bundle:
            with self.assertRaises(harness.HarnessError):
                harness._extract_validated_tar(bundle, Path(tmp), "test")

    def test_git_checkout_detection_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            checkout = init_repo(Path(tmp) / "checkout")
            self.assertTrue(harness._is_git_checkout(checkout / "sub" if (checkout / "sub").mkdir() is None else checkout))
            plain = Path(tmp) / "plain"
            plain.mkdir()
            self.assertFalse(harness._is_git_checkout(plain))
            calls = []
            real_run = subprocess.run
            def capture(cmd, **kwargs):
                calls.append(kwargs.get("env", {}))
                return real_run(cmd, **kwargs)
            with patch.object(harness.subprocess, "run", side_effect=capture):
                harness._is_git_checkout(plain)
            self.assertEqual(calls[0].get("LC_ALL"), "C")  # message match must not depend on locale
            dubious = subprocess.CompletedProcess([], 128, stdout="", stderr="fatal: detected dubious ownership")
            with patch.object(harness.subprocess, "run", return_value=dubious):
                self.assertTrue(harness._is_git_checkout(plain))


if __name__ == "__main__":
    unittest.main()
