import importlib.util
from pathlib import Path, PureWindowsPath
import tempfile
import subprocess
import json
import copy
import hashlib
import os
import shutil
import sys
from unittest import mock
import unittest


PATH = Path(__file__).parents[1] / "tools" / "stack_install.py"
SPEC = importlib.util.spec_from_file_location("stack_install", PATH)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class InstallContracts(unittest.TestCase):
    def fixture_source(self, root):
        source = root / "source"
        (source / "tools").mkdir(parents=True)
        (source / "skills" / "sample").mkdir(parents=True)
        (source / "tools" / "tool.py").write_text("print('tool')\n")
        (source / "skills" / "sample" / "SKILL.md").write_text("# skill\n")
        (source / "strict-mode").mkdir()
        (source / "strict-mode" / "methodology.md").write_text("canon\n")
        (source / "schemas").mkdir()
        (source / "schemas" / "runtime.json").write_text("{}\n")
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        return source

    def test_plan_is_non_mutating_and_source_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            plan = installer.plan_runtime_install(source, target)
            self.assertFalse(target.exists())
            self.assertEqual(len(plan["source_digest"]), 64)
            self.assertEqual(plan["action"], "install-runtime")

    def test_apply_is_idempotent_records_private_inventory_and_preserves_existing_target_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"; inventory = root / "private"
            target.mkdir(); (target / "user-note").write_text("keep")
            plan = installer.plan_runtime_install(source, target)
            first = installer.apply_runtime_plan(plan, inventory_root=inventory)
            second = installer.apply_runtime_plan(plan, inventory_root=inventory)
            self.assertTrue((target / "user-note").exists())
            self.assertTrue((target / "tools" / "tool.py").exists())
            self.assertTrue(first["verified"] and second["verified"])
            self.assertEqual((inventory.stat().st_mode & 0o077), 0)

    def test_source_mutation_rejects_apply_before_target_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            plan = installer.plan_runtime_install(source, target)
            (source / "tools" / "tool.py").write_text("changed\n")
            with self.assertRaises(installer.InstallError):
                installer.apply_runtime_plan(plan, inventory_root=root / "private")
            self.assertFalse(target.exists())

    def test_project_init_preserves_dirty_files_and_respects_explicit_disabled_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); repo = root / "repo"; repo.mkdir()
            (repo / "AGENTS.md").write_text("custom rules\n")
            (repo / ".agent").mkdir(); (repo / ".agent" / ".strict-mode").write_text("off\n")
            result = installer.initialize_project(source, repo, apply=True)
            self.assertEqual((repo / "AGENTS.md").read_text(), "custom rules\n")
            self.assertEqual(result["state"], "disabled")

    def test_partial_apply_rolls_back_managed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            installer.apply_runtime_plan(installer.plan_runtime_install(source, target), inventory_root=root / "private")
            before = self.snapshot(target)
            (source / "tools/tool.py").write_text("upgrade\n")
            plan = installer.plan_runtime_install(source, target)
            with self.assertRaises(installer.InstallError):
                installer.apply_runtime_plan(plan, inventory_root=root / "private", fail_after=1)
            self.assertEqual(self.snapshot(target), before)

    def test_payload_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            (source / "tools" / "link.py").symlink_to(source / "tools" / "tool.py")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            with self.assertRaises(installer.InstallError): installer.plan_runtime_install(source, root / "target")

    def test_tampered_plan_types_paths_and_inventory_fail_before_writes(self):
        mutations = [
            lambda p: p.update(source=3),
            lambda p: p.update(payload="tools/tool.py"),
            lambda p: p["payload"].append(["../escaped", "x", 420]),
            lambda p: p["payload"].append(["/tmp/escaped", "x", 420]),
            lambda p: p["payload"][0].__setitem__(1, "0" * 64),
            lambda p: p["payload"][0].__setitem__(2, 511),
            lambda p: p["payload"].pop(),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = self.fixture_source(root)
                plan = installer.plan_runtime_install(source, root / "target")
                mutate(plan)
                with self.assertRaises(installer.InstallError):
                    installer.apply_runtime_plan(plan, inventory_root=root / "private")
                self.assertFalse((root / "target").exists())
                self.assertFalse((root / "private").exists())

    def test_source_and_destination_parent_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            outside = root / "outside"; outside.mkdir()
            alias = root / "alias"; alias.symlink_to(root, target_is_directory=True)
            for a, b in [(alias / "source", root / "target"), (source, alias / "target")]:
                with self.assertRaises(installer.InstallError): installer.plan_runtime_install(a, b)
            target = root / "target"; target.mkdir()
            plan = installer.plan_runtime_install(source, target)
            (target / "tools").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(installer.InstallError): installer.plan_runtime_install(source, target)
            with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan, inventory_root=root / "private")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((root / "private").exists())

    def test_private_inventory_never_chmods_existing_or_writes_inside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            plan = installer.plan_runtime_install(source, root / "target")
            public = root / "public"; public.mkdir(mode=0o755)
            other = root / "other"; other.mkdir()
            subprocess.run(["git", "init", "-q", str(other)], check=True)
            for inventory in (public, source / "private", other / "private"):
                with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan, inventory_root=inventory)
            self.assertEqual(public.stat().st_mode & 0o777, 0o755)
            self.assertFalse((root / "target").exists())

    def test_public_payload_excludes_private_ignored_and_bytecode_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            for rel in ("tools/.env", "tools/private/token.json", "tools/__pycache__/tool.pyc", "skills/note.private"):
                path = source / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("SECRET_CANARY")
            subprocess.run(["git", "-C", str(source), "add", "tools"], check=True)
            plan = installer.plan_runtime_install(source, root / "target")
            self.assertFalse(any("SECRET_CANARY" in (source / entry[0]).read_text() for entry in plan["payload"]))
            installer.apply_runtime_plan(plan, inventory_root=root / "private")
            self.assertFalse((root / "target/tools/.env").exists())

    def test_bootstrap_files_follow_tracked_inventory_for_install_and_retirement(self):
        paths = ("tools/stack_install.py", "tools/stack_doctor.py",
                 "tools/stack_prepare.py", "strict-mode/bin/strict_init.py")
        for rel in paths:
            with self.subTest(path=rel), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
                candidate = source / rel
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("untracked bootstrap\n")
                plan = installer.plan_runtime_install(source, target)
                self.assertNotIn(rel, [entry[0] for entry in plan["payload"]])
                subprocess.run(["git", "-C", str(source), "add", rel], check=True)
                plan = installer.plan_runtime_install(source, target)
                self.assertIn(rel, [entry[0] for entry in plan["payload"]])
                installer.apply_runtime_plan(plan, inventory_root=root / "private")
                subprocess.run(["git", "-C", str(source), "rm", "--cached", "-q", rel], check=True)
                candidate.write_text("untracked local replacement\n")
                upgrade = installer.plan_runtime_install(source, target)
                self.assertNotIn(rel, [entry[0] for entry in upgrade["payload"]])
                installer.apply_runtime_plan(upgrade, inventory_root=root / "private")
                self.assertFalse((target / rel).exists())
                self.assertEqual(candidate.read_text(), "untracked local replacement\n")
                self.assertTrue(installer.verify_runtime_plan(upgrade))

    def test_managed_subset_preserves_secrets_and_runtime_replans_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            (target / "tools").mkdir(parents=True)
            (target / "tools/.env").write_text("SECRET_CANARY")
            (target / "tools/local.txt").write_text("keep")
            plan = installer.plan_runtime_install(source, target)
            installer.apply_runtime_plan(plan, inventory_root=root / "private")
            self.assertTrue(installer.verify_runtime_plan(plan))
            self.assertEqual((target / "tools/.env").read_text(), "SECRET_CANARY")
            self.assertEqual(installer.plan_runtime_install(target, root / "second")["payload"], plan["payload"])

    def test_every_write_failure_restores_bytes_modes_version_receipt_and_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            plan = installer.plan_runtime_install(source, root / "target")
            count = len(plan["payload"]) + 3
            for failure in range(1, count + 1):
                with self.subTest(failure=failure):
                    target = root / "target"
                    with self.assertRaisesRegex(installer.InstallError, "injected"):
                        installer.apply_runtime_plan(plan, inventory_root=root / "private/nested", fail_after=failure)
                    self.assertFalse(target.exists())
                    self.assertFalse((root / "private").exists())

    def test_duplicate_runtime_inventory_fields_reject_before_writes_and_doctor_fails_closed(self):
        doctor_spec = importlib.util.spec_from_file_location("inventory_doctor", PATH.with_name("stack_doctor.py"))
        doctor = importlib.util.module_from_spec(doctor_spec); doctor_spec.loader.exec_module(doctor)
        prefixes = {
            "payload": '{"payload": [],',
            "source_digest": '{"source_digest": "' + '0' * 64 + '",',
            "nested": '{"extra": {"value": 1, "value": 2},',
            "escaped": '{"\\u0070ayload": [],',
        }
        for kind, prefix in prefixes.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = self.fixture_source(root)
                runtime, target = root / "runtime", root / "target"
                installer.apply_runtime_plan(installer.plan_runtime_install(source, runtime), inventory_root=root / "seed-private")
                plan = installer.plan_runtime_install(runtime, target)
                valid_digest = installer._digest(runtime)
                report = doctor.inspect(root, runtime=runtime)
                self.assertEqual(report["runtime"]["source_digest"], valid_digest)
                self.assertNotIn("runtime_inventory_invalid", report["unresolved"])
                manifest = runtime / installer._MANIFEST
                original = manifest.read_text()
                manifest.write_text(prefix + original[1:])
                before = self.snapshot(root)
                with self.assertRaisesRegex(installer.InstallError, "invalid runtime inventory"):
                    installer.apply_runtime_plan(plan, inventory_root=root / "private")
                self.assertEqual(self.snapshot(root), before)
                self.assertFalse(target.exists()); self.assertFalse((root / "private").exists())
                report = doctor.inspect(root, runtime=runtime)
                self.assertIsNone(report["runtime"]["source_digest"])
                self.assertIn("runtime_inventory_invalid", report["unresolved"])
                self.assertEqual(self.snapshot(root), before)
                manifest.write_text(original)
                installer.apply_runtime_plan(plan, inventory_root=root / "private")
                self.assertTrue(installer.verify_runtime_plan(plan))

    def test_duplicate_receipt_fields_remain_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            target, private = root / "target", root / "private"
            plan = installer.plan_runtime_install(source, target)
            installer.apply_runtime_plan(plan, inventory_root=private)
            receipt = installer.runtime_receipt_path(private, plan["source_digest"], target)
            receipt.write_text('{"verified": false,' + receipt.read_text()[1:])
            before = self.snapshot(root)
            with self.assertRaisesRegex(installer.InstallError, "private receipt collision"):
                installer.apply_runtime_plan(plan, inventory_root=private)
            self.assertEqual(self.snapshot(root), before)

    def test_standalone_runtime_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            plan = installer.plan_runtime_install(source, target)
            installer.apply_runtime_plan(plan, inventory_root=root / "private")
            (target / "tools/tool.py").write_text("tampered")
            with self.assertRaises(installer.InstallError): installer.plan_runtime_install(target, root / "second")

    def test_support_docs_are_explicit_not_a_whole_docs_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            (source / "docs").mkdir()
            (source / "docs/canon.md").write_text("public canon")
            (source / "docs/private-research.md").write_text("private research")
            subprocess.run(["git", "-C", str(source), "add", "docs"], check=True)
            names = [item[0] for item in installer.plan_runtime_install(source, root / "target")["payload"]]
            self.assertIn("docs/canon.md", names)
            self.assertNotIn("docs/private-research.md", names)

    def test_disable_marker_parity_uses_first_line_and_untracked_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            repo = root / "consumer"; repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / ".agent").mkdir(); marker = repo / ".agent/.strict-mode"
            marker.write_text("off\nuser explanation\n")
            self.assertEqual(installer.initialize_project(source, repo, apply=True)["state"], "disabled")
            subprocess.run(["git", "-C", str(repo), "add", "-f", ".agent/.strict-mode"], check=True)
            self.assertEqual(installer.initialize_project(source, repo)["state"], "planned")
            self.assertEqual(marker.read_text(), "off\nuser explanation\n")

    def test_project_init_resolves_disabled_root_from_subdirectory_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            source = self.fixture_source(base)
            repo, wrong = base / "consumer", base / "wrong"
            for target in (repo, wrong):
                subprocess.run(["git", "init", "-q", str(target)], check=True)
            child = repo / "packages" / "app"
            child.mkdir(parents=True)
            (repo / ".agent").mkdir()
            (repo / ".agent/.strict-mode").write_text("off\nuser decision\n")
            snapshot = lambda: {str(path.relative_to(base)): (path.read_bytes(), path.stat().st_mode)
                                for path in base.rglob("*") if path.is_file()}
            before = snapshot()
            contamination = {"GIT_DIR": str(wrong / ".git"), "GIT_WORK_TREE": str(wrong),
                             "GIT_INDEX_FILE": str(wrong / ".git/index"), "GIT_CONFIG_COUNT": "1",
                             "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/must-not-use"}
            with mock.patch.dict(os.environ, contamination):
                for target in (repo, child):
                    self.assertEqual(installer.initialize_project(source, target, apply=True),
                                     {"state": "disabled", "changed": False})
            self.assertEqual(snapshot(), before)
            self.assertFalse((child / ".agent").exists())
            nongit = base / "nongit"
            nongit.mkdir()
            self.assertEqual(installer.initialize_project(source, nongit)["state"], "planned")
            failures = (OSError("Git unavailable"), subprocess.TimeoutExpired(["git"], 30))
            for failure in failures:
                with self.subTest(failure=type(failure).__name__), mock.patch.object(installer.subprocess, "run", side_effect=failure):
                    with self.assertRaisesRegex(installer.InstallError, "Git root"):
                        installer.initialize_project(source, child, apply=True)
            result = subprocess.CompletedProcess(["git"], 128, "", "fatal: detected dubious ownership")
            with mock.patch.object(installer.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(installer.InstallError, "Git root"):
                    installer.initialize_project(source, child, apply=True)
            self.assertEqual(snapshot(), before)

    def test_inherited_git_repository_environment_cannot_redirect_install_or_child_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root)
            shutil.copytree(PATH.parents[1] / "strict-mode", source / "strict-mode", dirs_exist_ok=True)
            subprocess.run(["git", "-C", str(source), "add", "strict-mode"], check=True)
            wrong = root / "wrong"; wrong.mkdir()
            subprocess.run(["git", "init", "-q", str(wrong)], check=True)
            repo = root / "consumer"; repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            before = (wrong / ".git/config").read_bytes()
            contamination = {"GIT_DIR": str(wrong / ".git"), "GIT_WORK_TREE": str(wrong), "GIT_INDEX_FILE": str(wrong / ".git/index"), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/must-not-use"}
            with mock.patch.dict(os.environ, contamination):
                plan = installer.plan_runtime_install(source, root / "runtime")
                installer.apply_runtime_plan(plan, inventory_root=root / "private")
                self.assertEqual(installer.initialize_project(source, repo, apply=True)["state"], "initialized")
            self.assertEqual((wrong / ".git/config").read_bytes(), before)
            self.assertFalse((wrong / ".agent").exists())
            self.assertEqual((repo / ".agent/.strict-version").read_text(), "3\n")

    def test_version_is_never_activated_before_failed_payload_or_manifest_verification(self):
        for corrupt_manifest in (False, True):
            with self.subTest(manifest=corrupt_manifest), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
                plan = installer.plan_runtime_install(source, target)
                original_replace = installer.os.replace
                activations = []
                def replace(src, dest):
                    dest = Path(dest)
                    if dest == target / "VERSION":
                        activations.append(Path(src).read_bytes())
                    original_replace(src, dest)
                    if dest == target / installer._MANIFEST:
                        if corrupt_manifest:
                            dest.write_text("{}")
                        else:
                            (target / plan["payload"][0][0]).write_text("corruption")
                with mock.patch.object(installer.os, "replace", side_effect=replace):
                    with self.assertRaises(installer.InstallError):
                        installer.apply_runtime_plan(plan, inventory_root=root / "private")
                self.assertNotIn(b"3\n", activations)
                self.assertFalse(target.exists())

    def test_upgrade_retires_only_previously_managed_files_and_rolls_back_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            installer.apply_runtime_plan(installer.plan_runtime_install(source,target),inventory_root=root/'private')
            old = target/'tools/tool.py'; original=old.read_bytes(); old_manifest=(target/installer._MANIFEST).read_bytes()
            (target/'tools/user-script.py').write_text('user-owned extra\n')
            subprocess.run(['git','-C',str(source),'rm','-q','-f','tools/tool.py'],check=True)
            (source/'tools').mkdir(exist_ok=True)
            (source/'tools/replacement.py').write_text('replacement\n')
            subprocess.run(['git','-C',str(source),'add','tools/replacement.py'],check=True)
            plan=installer.plan_runtime_install(source,target)
            with self.assertRaises(installer.InstallError):
                installer.apply_runtime_plan(plan,inventory_root=root/'private',fail_after=1)
            self.assertEqual(old.read_bytes(),original)
            self.assertEqual((target/installer._MANIFEST).read_bytes(),old_manifest)
            installer.apply_runtime_plan(plan,inventory_root=root/'private')
            self.assertFalse(old.exists())
            self.assertTrue((target/'tools/replacement.py').is_file())
            self.assertEqual((target/'tools/user-script.py').read_text(),'user-owned extra\n')
            self.assertTrue(installer.verify_runtime_plan(plan))
            installer.apply_runtime_plan(plan,inventory_root=root/'private')
            old.write_bytes(original)
            self.assertFalse(installer.verify_runtime_plan(plan))

    def test_modified_retired_managed_file_rejects_upgrade_without_deleting_user_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
            installer.apply_runtime_plan(installer.plan_runtime_install(source,target),inventory_root=root/'private')
            subprocess.run(['git','-C',str(source),'rm','-q','-f','tools/tool.py'],check=True)
            (source/'tools').mkdir(exist_ok=True)
            (source/'tools/replacement.py').write_text('replacement\n')
            subprocess.run(['git','-C',str(source),'add','tools/replacement.py'],check=True)
            plan=installer.plan_runtime_install(source,target)
            (target/'tools/tool.py').write_text('local customized content\n')
            with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan,inventory_root=root/'private')
            self.assertEqual((target/'tools/tool.py').read_text(),'local customized content\n')

    def snapshot(self, root):
        return {str(p.relative_to(root)): ('dir' if p.is_dir() else p.read_bytes(), p.stat().st_mode & 0o777)
                for p in root.rglob('*')}

    def test_unowned_payload_and_metadata_collisions_reject_before_writes(self):
        for rel in ('tools/tool.py', 'VERSION', installer._MANIFEST):
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
                plan=installer.plan_runtime_install(source,target)
                collision=target/rel; collision.parent.mkdir(parents=True); collision.write_text('unowned bytes\n'); collision.chmod(0o600)
                before=self.snapshot(target)
                with self.assertRaises(installer.InstallError):
                    installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertEqual(self.snapshot(target),before)
                self.assertFalse((root/'private').exists())

    def transition_fixture(self, root, directory_to_file):
        source=self.fixture_source(root); target=root/'target'
        old='tools/foo/nested/item.py' if directory_to_file else 'tools/foo'
        new='tools/foo' if directory_to_file else 'tools/foo/nested/item.py'
        path=source/old; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('old managed\n'); path.chmod(0o750)
        subprocess.run(['git','-C',str(source),'add','.'],check=True)
        installer.apply_runtime_plan(installer.plan_runtime_install(source,target),inventory_root=root/'private')
        if directory_to_file:
            (target/'tools/foo').chmod(0o710); (target/'tools/foo/nested').chmod(0o700)
        subprocess.run(['git','-C',str(source),'rm','-q','-f',old],check=True)
        path=source/new; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('new managed\n'); path.chmod(0o640)
        subprocess.run(['git','-C',str(source),'add','.'],check=True)
        return source,target,installer.plan_runtime_install(source,target)

    def test_managed_path_type_transitions_verify_repeat_and_rollback_every_write(self):
        for directory_to_file in (True,False):
            with self.subTest(directory_to_file=directory_to_file), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source,target,plan=self.transition_fixture(root,directory_to_file)
                before=self.snapshot(target); private_before=self.snapshot(root/'private')
                for failure in range(1,len(plan['payload'])+4):
                    with self.subTest(failure=failure):
                        with self.assertRaises(installer.InstallError):
                            installer.apply_runtime_plan(plan,inventory_root=root/'private',fail_after=failure)
                        self.assertEqual(self.snapshot(target),before)
                        self.assertEqual(self.snapshot(root/'private'),private_before)
                installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertTrue(installer.verify_runtime_plan(plan))
                after=self.snapshot(target)
                installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertEqual(self.snapshot(target),after)
                self.assertTrue(installer.verify_runtime_plan(plan))

    def test_directory_transition_rejects_unmanaged_children_before_mutation(self):
        for extra in ('secret.env','empty-dir','alias'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source,target,plan=self.transition_fixture(root,True)
                path=target/'tools/foo'/extra
                if extra=='empty-dir': path.mkdir()
                elif extra=='alias': path.symlink_to(target/'tools/tool.py')
                else: path.write_text('private preserved\n')
                before=self.snapshot(target); private_before=self.snapshot(root/'private')
                with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertEqual(self.snapshot(target),before)
                self.assertEqual(self.snapshot(root/'private'),private_before)

    def test_upgrade_retained_bytes_modes_and_metadata_drift_are_never_overwritten(self):
        for rel, mode_only in (("tools/tool.py", False), ("tools/tool.py", True), ("VERSION", False), ("VERSION", True), (installer._MANIFEST, False)):
            with self.subTest(rel=rel, mode_only=mode_only), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
                installer.apply_runtime_plan(installer.plan_runtime_install(source,target),inventory_root=root/'private')
                (source/'tools/tool.py').write_text('upgrade\n')
                plan=installer.plan_runtime_install(source,target)
                path=target/rel
                if mode_only: path.chmod(0o600)
                else: path.write_bytes(path.read_bytes()+b'local bytes\n')
                before=self.snapshot(target); private_before=self.snapshot(root/'private')
                with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertEqual(self.snapshot(target),before)
                self.assertEqual(self.snapshot(root/'private'),private_before)

    def test_upgrade_new_path_collision_and_identical_unowned_file_reject(self):
        for upgrade in (False,True):
            with self.subTest(upgrade=upgrade), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
                if upgrade: installer.apply_runtime_plan(installer.plan_runtime_install(source,target),inventory_root=root/'private')
                rel='tools/new.py' if upgrade else 'tools/tool.py'
                (source/rel).write_text('identical yet unowned\n')
                subprocess.run(['git','-C',str(source),'add','.'],check=True)
                path=target/rel; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes((source/rel).read_bytes())
                plan=installer.plan_runtime_install(source,target); before=self.snapshot(target)
                with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertEqual(self.snapshot(target),before)

    def test_private_receipt_collision_preserved_and_known_receipt_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
            plan=installer.plan_runtime_install(source,target); private=root/'private'; private.mkdir(mode=0o700)
            receipt=installer.runtime_receipt_path(private,plan['source_digest'],target)
            receipt.write_text('unrelated private bytes\n'); receipt.chmod(0o600)
            before=self.snapshot(private)
            with self.assertRaises(installer.InstallError): installer.apply_runtime_plan(plan,inventory_root=private)
            self.assertEqual(self.snapshot(private),before); self.assertFalse(target.exists())
            receipt.unlink()
            installer.apply_runtime_plan(plan,inventory_root=private)
            # Replanning an installed upgrade can have a different retirement list.
            record=json.loads(receipt.read_text()); record['retired_files']=['tools/old.py']
            receipt.write_text(json.dumps(record,sort_keys=True)+'\n')
            before=self.snapshot(private)
            installer.apply_runtime_plan(installer.plan_runtime_install(source,target),inventory_root=private)
            self.assertEqual(self.snapshot(private),before)

    def test_runtime_verification_requires_activation_metadata_bytes_and_modes(self):
        for mutation in ('missing-version', 'wrong-version', 'version-mode', 'manifest-mode', 'manifest-format', 'version-symlink'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
                plan=installer.plan_runtime_install(source,target)
                installer.apply_runtime_plan(plan,inventory_root=root/'private')
                self.assertTrue(installer.verify_runtime_plan(plan))
                version=target/'VERSION'; manifest=target/installer._MANIFEST
                if mutation=='missing-version': version.unlink()
                elif mutation=='wrong-version': version.write_text('2\n')
                elif mutation=='version-mode': version.chmod(0o600)
                elif mutation=='manifest-mode': manifest.chmod(0o600)
                elif mutation=='manifest-format': manifest.write_text(manifest.read_text()+'\n')
                else:
                    copy=target/'local-version'; copy.write_bytes(version.read_bytes())
                    version.unlink(); version.symlink_to(copy)
                self.assertFalse(installer.verify_runtime_plan(plan))

    def test_nonregular_private_receipt_rejects_without_blocking_or_mutation(self):
        for kind in ('fifo', 'directory'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); source=self.fixture_source(root); target=root/'target'
                plan=installer.plan_runtime_install(source,target); private=root/'private'; private.mkdir(mode=0o700)
                receipt=installer.runtime_receipt_path(private,plan['source_digest'],target)
                if kind == 'fifo': os.mkfifo(receipt, 0o600)
                else: receipt.mkdir(mode=0o700)
                before=receipt.stat()
                code=("from pathlib import Path\nfrom tools.stack_install import apply_runtime_plan, InstallError\n"
                      "try:\n apply_runtime_plan("+repr(plan)+",inventory_root=Path("+repr(str(private))+"))\n"
                      "except InstallError:\n raise SystemExit(0)\nraise SystemExit(1)\n")
                result=subprocess.run([sys.executable,'-c',code],cwd=PATH.parents[1],capture_output=True,timeout=3)
                self.assertEqual(result.returncode,0,result.stderr)
                after=receipt.stat()
                self.assertEqual((before.st_ino,before.st_mode),(after.st_ino,after.st_mode))
                self.assertEqual(list(private.iterdir()),[receipt]); self.assertFalse(target.exists())

    def test_failed_directory_removal_restores_retired_files_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source,target,plan=self.transition_fixture(root,True)
            before=self.snapshot(target); private_before=self.snapshot(root/'private')
            original=Path.rmdir
            def fail(path):
                if path == target/'tools/foo':
                    raise OSError('injected directory removal failure')
                return original(path)
            with mock.patch.object(Path,'rmdir',fail):
                with self.assertRaisesRegex(OSError,'injected directory removal'):
                    installer.apply_runtime_plan(plan,inventory_root=root/'private')
            self.assertEqual(self.snapshot(target),before)
            self.assertEqual(self.snapshot(root/'private'),private_before)

    def test_same_payload_two_targets_share_inventory_without_receipt_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source=self.fixture_source(root); private=root/'private'
            first=installer.plan_runtime_install(source,root/'first')
            second=installer.plan_runtime_install(source,root/'second')
            installer.apply_runtime_plan(first,inventory_root=private)
            before=self.snapshot(private); first_before=self.snapshot(root/'first')
            with self.assertRaisesRegex(installer.InstallError,'injected receipt failure'):
                installer.apply_runtime_plan(second,inventory_root=private,fail_after=len(second['payload'])+3)
            self.assertEqual(self.snapshot(private),before)
            self.assertEqual(self.snapshot(root/'first'),first_before)
            self.assertFalse((root/'second').exists())
            installer.apply_runtime_plan(second,inventory_root=private)
            self.assertTrue(installer.verify_runtime_plan(first)); self.assertTrue(installer.verify_runtime_plan(second))
            receipts=list(private.glob('runtime-*.json'))
            self.assertEqual(len(receipts),2)
            self.assertEqual({json.loads(p.read_text())['target'] for p in receipts},{first['target'],second['target']})
            before=self.snapshot(private)
            installer.apply_runtime_plan(first,inventory_root=private)
            alias=installer.plan_runtime_install(source,root/'second/../second')
            installer.apply_runtime_plan(alias,inventory_root=private)
            self.assertEqual(self.snapshot(private),before)

    def test_legacy_source_only_receipts_are_preserved_without_target_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source=self.fixture_source(root); private=root/'private'; private.mkdir(mode=0o700)
            plan=installer.plan_runtime_install(source,root/'target')
            legacy=private/('runtime-'+plan['source_digest'][:16]+'.json')
            legacy.write_text('existing private receipt retained\n'); legacy.chmod(0o600)
            before=(legacy.read_bytes(),legacy.stat().st_mode,legacy.stat().st_ino)
            installer.apply_runtime_plan(plan,inventory_root=private)
            self.assertEqual((legacy.read_bytes(),legacy.stat().st_mode,legacy.stat().st_ino),before)
            self.assertEqual(len(list(private.glob('runtime-*.json'))),2)
            self.assertTrue(installer.verify_runtime_plan(plan))

    def test_non_git_activation_fails_without_writing_a_partial_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            (target / "notes.txt").write_text("preserve existing work\n")
            (target / ".env").write_text("FIXTURE_SETTING=preserve\n")
            before = self.snapshot(target)
            with self.assertRaises(installer.InstallError):
                installer.initialize_project(PATH.parents[1], target, apply=True)
            self.assertEqual(self.snapshot(target), before)

    def test_git_ceiling_cannot_hide_repository_contained_runtime_or_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source=self.fixture_source(root); repo=root/'other-repo'
            subprocess.run(['git','init','-q',str(repo)],check=True)
            nested=repo/'nested'; nested.mkdir()
            runtime=nested/'runtime'; inventory=nested/'private'
            outside=root/'outside-runtime'
            plan=installer.plan_runtime_install(source,outside)
            before=self.snapshot(repo)
            with mock.patch.dict(os.environ,{'GIT_CEILING_DIRECTORIES':str(repo)}):
                with self.subTest(destination='runtime'), self.assertRaises(installer.InstallError):
                    installer.plan_runtime_install(source,runtime)
                with self.subTest(destination='inventory'), self.assertRaises(installer.InstallError):
                    installer.apply_runtime_plan(plan,inventory_root=inventory)
            self.assertEqual(self.snapshot(repo),before)
            self.assertFalse(outside.exists())

    def test_git_environment_allowlist_retains_user_config_without_discovery_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); global_config=root/'global-config'; system_config=root/'system-config'
            global_config.write_text('[user]\n\tname = Fixture global identity\n')
            system_config.write_text('')
            chosen = {'GIT_CONFIG_GLOBAL': str(global_config), 'GIT_CONFIG_SYSTEM': str(system_config), 'GIT_CONFIG_NOSYSTEM': '1'}
            injected = {**chosen, 'GIT_CEILING_DIRECTORIES': str(root), 'GIT_DISCOVERY_ACROSS_FILESYSTEM': '1',
                        'GIT_NAMESPACE': 'foreign', 'GIT_CONFIG_PARAMETERS': 'invalid inherited config',
                        'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/foreign',
                        'GIT_FUTURE_DISCOVERY_OVERRIDE': 'must not propagate', 'CAPHE_FIXTURE_SETTING': 'preserved'}
            with mock.patch.dict(os.environ, injected):
                environment = installer._git_env()
                self.assertEqual({key: value for key, value in environment.items() if key.startswith('GIT_')}, chosen)
                self.assertEqual(environment['CAPHE_FIXTURE_SETTING'], 'preserved')
                result = subprocess.run(['git', 'config', '--global', '--get', 'user.name'],
                                        env=environment, capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout.strip(), 'Fixture global identity')

    def test_malformed_global_config_cannot_hide_physical_git_ancestors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source=self.fixture_source(root); repo=root/'other-repo'
            subprocess.run(['git','init','-q',str(repo)],check=True)
            nested=repo/'nested'; nested.mkdir()
            config=root/'malformed-global'; config.write_text('[malformed\n')
            before=self.snapshot(repo)
            with mock.patch.dict(os.environ,{'GIT_CONFIG_GLOBAL':str(config)}):
                with self.subTest(destination='runtime'), self.assertRaises(installer.InstallError):
                    installer._outside_git(nested/'runtime')
                with self.subTest(destination='inventory'), self.assertRaises(installer.InstallError):
                    installer._private_preflight(nested/'private',source,root/'runtime')
            self.assertEqual(self.snapshot(repo),before)

    def test_unknown_git_discovery_under_malformed_global_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); source=self.fixture_source(root)
            config=root/'malformed-global'; config.write_text('[malformed\n')
            with mock.patch.dict(os.environ,{'GIT_CONFIG_GLOBAL':str(config), 'LC_ALL':'fr_FR.UTF-8'}):
                with self.subTest(destination='runtime'), self.assertRaises(installer.InstallError):
                    installer._outside_git(root/'runtime')
                with self.subTest(destination='inventory'), self.assertRaises(installer.InstallError):
                    installer._private_preflight(root/'private',source,root/'runtime')
            self.assertFalse((root/'runtime').exists()); self.assertFalse((root/'private').exists())

    def test_nested_git_payload_destination_rejects_plan_and_apply_before_writes(self):
        for kind in ("normal", "malformed", "bare"):
            for action in ("plan", "apply"):
                with self.subTest(kind=kind, action=action), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
                    plan = installer.plan_runtime_install(source, target)
                    nested = target / "tools"; nested.mkdir(parents=True)
                    if kind == "malformed":
                        (nested / ".git").write_text("not a valid Git marker\n")
                    else:
                        subprocess.run(["git", "init", "-q", *(["--bare"] if kind == "bare" else []), str(nested)], check=True)
                    before = self.snapshot(target)
                    with self.assertRaises(installer.InstallError):
                        if action == "plan": installer.plan_runtime_install(source, target)
                        else: installer.apply_runtime_plan(plan, inventory_root=root / "private")
                    self.assertEqual(self.snapshot(target), before)
                    self.assertFalse((root / "private").exists())

    def test_nested_git_retired_destination_rejects_upgrade_and_repeat_verification(self):
        for after_upgrade in (False, True):
            with self.subTest(after_upgrade=after_upgrade), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
                old = source / "tools/retired/item.py"; old.parent.mkdir(); old.write_text("retired\n")
                subprocess.run(["git", "-C", str(source), "add", "."], check=True)
                installer.apply_runtime_plan(installer.plan_runtime_install(source, target), inventory_root=root / "private")
                subprocess.run(["git", "-C", str(source), "rm", "-q", "--cached", "tools/retired/item.py"], check=True)
                old.unlink()
                plan = installer.plan_runtime_install(source, target)
                if after_upgrade:
                    installer.apply_runtime_plan(plan, inventory_root=root / "private")
                nested = target / "tools/retired"
                subprocess.run(["git", "init", "-q", str(nested)], check=True)
                before = self.snapshot(root)
                with self.assertRaises(installer.InstallError):
                    installer.apply_runtime_plan(plan, inventory_root=root / "private")
                with self.assertRaises(installer.InstallError):
                    installer.verify_runtime_plan(plan)
                self.assertEqual(self.snapshot(root), before)

    def test_existing_managed_boundary_probes_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            installer.apply_runtime_plan(installer.plan_runtime_install(source, target), inventory_root=root / "private")
            plan = installer.plan_runtime_install(source, target)
            original = installer._outside_git
            with mock.patch.object(installer, "_outside_git", wraps=original) as probe:
                installer.verify_runtime_plan(plan)
            directories = [call.args[0] for call in probe.call_args_list]
            self.assertEqual(len(directories), len(set(directories)))

    def test_git_directory_at_payload_or_metadata_leaf_rejects_without_mutation(self):
        for relative in ("tools/tool.py", "VERSION", installer._MANIFEST):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
                plan = installer.plan_runtime_install(source, target)
                nested = target / relative; nested.mkdir(parents=True)
                subprocess.run(["git", "init", "-q", str(nested)], check=True)
                before = self.snapshot(target)
                with self.assertRaises(installer.InstallError):
                    installer.apply_runtime_plan(plan, inventory_root=root / "private")
                self.assertEqual(self.snapshot(target), before)
                self.assertFalse((root / "private").exists())

    def test_unmanaged_git_subtree_outside_managed_destinations_remains_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "target"
            unrelated = target / "user-notes"; unrelated.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(unrelated)], check=True)
            (unrelated / "note").write_text("keep\n")
            before = self.snapshot(unrelated)
            plan = installer.plan_runtime_install(source, target)
            installer.apply_runtime_plan(plan, inventory_root=root / "private")
            self.assertTrue(installer.verify_runtime_plan(plan))
            self.assertEqual(self.snapshot(unrelated), before)

    def test_public_payload_names_reject_windows_separators_drives_streams_and_nul(self):
        escape = "tools/a" + "\\.." * 3 + "\\victim"
        selected = PureWindowsPath("C:/selected/runtime")
        # Windows treats the POSIX-accepted spelling as parent traversal.
        parts = []
        for part in (selected / escape).parts:
            if part == "..": parts.pop()
            else: parts.append(part)
        self.assertFalse(PureWindowsPath(*parts).is_relative_to(selected))
        for relative in (escape, "tools/C:relative", "tools/file:stream", "tools/nul" + chr(0) + ".py"):
            with self.subTest(relative=relative):
                self.assertFalse(installer._public(relative))

    def test_ambiguous_standalone_payload_names_reject_before_install_or_retirement(self):
        for relative in ("tools/a" + "\\.." * 3 + "\\victim", "tools/file:stream", "tools/C:relative", "tools/nul" + chr(0) + ".py"):
            for use_as in ("source", "previous"):
                with self.subTest(relative=relative, use_as=use_as), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve(); source = self.fixture_source(root); runtime = root / "runtime"
                    installer.apply_runtime_plan(installer.plan_runtime_install(source, runtime), inventory_root=root / "seed-private")
                    target = root / "target" if use_as == "source" else runtime
                    distribution = runtime if use_as == "source" else source
                    plan = installer.plan_runtime_install(distribution, target)
                    # POSIX permits these literal filenames; a standalone inventory
                    # must not authorize their alternate Windows interpretation.
                    content = b"preserve unowned bytes\n"
                    if chr(0) not in relative:
                        extra = runtime / relative; extra.write_bytes(content); extra.chmod(0o644)
                    metadata = runtime / installer._MANIFEST
                    record = json.loads(metadata.read_text())
                    record["payload"].append([relative, hashlib.sha256(content).hexdigest(), 0o644])
                    record["payload"].sort()
                    record["source_digest"] = installer._entries_digest(record["payload"])
                    metadata.write_text(json.dumps(record))
                    before = self.snapshot(root)
                    with self.assertRaises(installer.InstallError):
                        installer.plan_runtime_install(distribution, target)
                    with self.assertRaises(installer.InstallError):
                        installer.apply_runtime_plan(plan, inventory_root=root / "private")
                    self.assertEqual(self.snapshot(root), before)
                    self.assertFalse((root / "private").exists())

    def test_ambiguous_payload_paths_reject_before_filesystem_interpretation(self):
        for relative in ("tools/a\\..\\victim", "tools/file:stream", "tools/nul" + chr(0)):
            with self.subTest(relative=relative), mock.patch.object(installer, "_safe_path", side_effect=AssertionError("filesystem queried")):
                with self.assertRaises(installer.InstallError):
                    installer._payload_path(Path("selected"), relative)

    def test_runtime_and_inventory_reject_canonical_store_aliases_before_payload_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); home = root / "home"; home.mkdir()
            target = root / "runtime"
            plan = installer.plan_runtime_install(source, target)
            canonical = home / ".codex/memories"; canonical.mkdir(parents=True, mode=0o700)
            (canonical / "record.json").write_text('{"fixture":"preserve"}\n')
            forbidden = [root, home, home.with_name("HOME"), home / ".CoDeX"]
            for relative in (".codex/memories/install", ".CODEX/MEMORIES/install", ".codex/sessions/install", ".CoDeX/SeSsIoNs/install"):
                forbidden.extend((home / relative, root / "other-home" / relative))
            forbidden.append(home / "nested/../.CODEX/MEMORIES/install")
            before = self.snapshot(root)
            with mock.patch.object(installer.Path, "home", return_value=home):
                for destination in forbidden:
                    with self.subTest(destination=destination):
                        with mock.patch.object(installer, "_payload", side_effect=AssertionError("payload read before canonical-store rejection")):
                            with self.assertRaisesRegex(installer.InstallError, "canonical"):
                                installer.plan_runtime_install(source, destination)
                            stale = copy.deepcopy(plan); stale["target"] = str(destination)
                            with self.assertRaisesRegex(installer.InstallError, "canonical"):
                                installer.apply_runtime_plan(stale, inventory_root=root / "private")
                        with self.assertRaisesRegex(installer.InstallError, "canonical"):
                            installer.apply_runtime_plan(plan, inventory_root=destination)
            self.assertEqual(self.snapshot(root), before)

    def test_canonical_store_sibling_names_remain_valid_install_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); home = root / "home"; home.mkdir()
            with mock.patch.object(installer.Path, "home", return_value=home):
                target = home / ".codex/memories-archive/runtime"
                inventory = home / ".codex/sessions-backup/inventory"
                plan = installer.plan_runtime_install(source, target)
                installer.apply_runtime_plan(plan, inventory_root=inventory)
                installer.apply_runtime_plan(plan, inventory_root=inventory)
                self.assertTrue(installer.verify_runtime_plan(plan))

    def test_private_inventory_rejects_mixed_case_canonical_store_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); home = root / "home"; home.mkdir()
            with mock.patch.object(installer.Path, "home", return_value=home):
                for relative in (".CODEX/MEMORIES/install", ".CoDeX/SeSsIoNs/install"):
                    with self.subTest(relative=relative), self.assertRaisesRegex(installer.InstallError, "canonical"):
                        installer._private_preflight(home / relative, source, root / "target")

    def test_return_to_previous_payload_keeps_transition_receipts_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = self.fixture_source(root); target = root / "runtime"; private = root / "private"
            def select(name):
                for prior in ("a", "b", "c"):
                    relative = "tools/release-" + prior + ".py"
                    if (source / relative).exists():
                        subprocess.run(["git", "-C", str(source), "rm", "-q", "--cached", relative], check=True)
                        (source / relative).unlink()
                (source / ("tools/release-" + name + ".py")).write_text(name + "\n")
                subprocess.run(["git", "-C", str(source), "add", "."], check=True)
                return installer.plan_runtime_install(source, target)
            def receipts():
                return {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino) for p in private.glob("runtime-*.json")}
            for version in ("a", "b", "c"):
                plan = select(version)
                installer.apply_runtime_plan(plan, inventory_root=private)
            before = receipts(); self.assertEqual(len(before), 3)
            previous_runtime = self.snapshot(target)
            plan = select("b")
            supplementary = installer.runtime_receipt_path(private, plan["source_digest"], target,
                                                           retired_files=["tools/release-c.py"])
            supplementary.write_text("unrelated private bytes\n"); supplementary.chmod(0o600)
            with self.assertRaisesRegex(installer.InstallError, "private receipt collision"):
                installer.apply_runtime_plan(plan, inventory_root=private)
            self.assertEqual(supplementary.read_text(), "unrelated private bytes\n")
            self.assertEqual(self.snapshot(target), previous_runtime)
            supplementary.unlink()  # Remove only this disposable collision fixture.
            with self.assertRaisesRegex(installer.InstallError, "injected receipt failure"):
                installer.apply_runtime_plan(plan, inventory_root=private, fail_after=len(plan["payload"]) + 3)
            self.assertEqual(receipts(), before)
            self.assertEqual(self.snapshot(target), previous_runtime)
            result = installer.apply_runtime_plan(plan, inventory_root=private)
            self.assertEqual(result["retired_files"], ["tools/release-c.py"])
            self.assertTrue(installer.verify_runtime_plan(plan))
            returned = receipts(); self.assertEqual(len(returned), 4)
            self.assertEqual({name: returned[name] for name in before}, before)
            installer.apply_runtime_plan(plan, inventory_root=private)
            installer.apply_runtime_plan(installer.plan_runtime_install(source, target), inventory_root=private)
            self.assertEqual(receipts(), returned)
            self.assertTrue((target / "tools/release-b.py").is_file())
            self.assertFalse((target / "tools/release-c.py").exists())
