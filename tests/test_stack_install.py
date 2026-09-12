import importlib.util
from pathlib import Path
import tempfile
import subprocess
import json
import copy
import os
import shutil
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
            (target / "tools").symlink_to(outside, target_is_directory=True)
            plan = installer.plan_runtime_install(source, target)
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
            receipt=private/('runtime-'+plan['source_digest'][:16]+'.json')
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
