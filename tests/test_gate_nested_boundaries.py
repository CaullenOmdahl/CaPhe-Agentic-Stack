"""Regressions for Git boundaries inside tracked paths and unstaged gitlink replacements."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("gate_nested_boundaries", ROOT / "strict-mode/bin/strict_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def git(root, *args):
    environment = gate.command_environment()
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.check_output(["git", *args], cwd=root, env=environment, text=True, stderr=subprocess.PIPE)


def initialize(root):
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")


def parent_tracked_child(root):
    initialize(root)
    child = root / "child"
    child.mkdir()
    (child / "source.txt").write_text("same working bytes")
    git(root, "add", ".")
    git(root, "commit", "-qm", "parent source")
    initialize(child)
    git(child, "add", ".")
    git(child, "commit", "-qm", "child source")
    return child


def indexed_gitlink(root, name="module"):
    initialize(root)
    module = root / name
    module.mkdir()
    initialize(module)
    (module / "source.txt").write_text("original source")
    git(module, "add", ".")
    git(module, "commit", "-qm", "module source")
    revision = git(module, "rev-parse", "HEAD").strip()
    git(root, "update-index", "--add", "--cacheinfo", "160000," + revision + "," + name)
    git(root, "commit", "-qm", "parent gitlink")
    shutil.rmtree(module)
    return module


class NestedBoundaryTests(unittest.TestCase):
    def test_embedded_repo_inside_parent_tracked_directory_binds_child_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = parent_tracked_child(root)
            self.assertEqual(git(root, "ls-files").splitlines(), ["child/source.txt"])
            before = gate.snapshot_identity(root)
            git(child, "commit", "--allow-empty", "-qm", "child metadata change")
            after = gate.snapshot_identity(root)
            self.assertEqual(before["revision"], after["revision"])
            self.assertEqual((child / "source.txt").read_text(), "same working bytes")
            self.assertNotEqual(before["snapshot_digest"], after["snapshot_digest"])

    def test_embedded_repo_inside_parent_tracked_directory_binds_child_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = parent_tracked_child(root)
            before = gate.snapshot_identity(root)
            git(child, "rm", "--cached", "source.txt")
            after = gate.snapshot_identity(root)
            self.assertEqual((child / "source.txt").read_text(), "same working bytes")
            self.assertEqual(git(root, "diff", "--name-only"), "")
            self.assertNotEqual(before["snapshot_digest"], after["snapshot_digest"])

    def test_child_empty_commit_during_completion_marks_source_stale(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            root = Path(tmp)
            child = parent_tracked_child(root)
            report_path = Path(state).resolve() / "report.json"
            command = gate.CommandSpec("fixture", "commit-child", ("git", "commit", "--allow-empty", "-qm", "during checks"), cwd="child")
            result = gate.execute_plan(root, [command], "manifest", 1, mode="completion", report_path=report_path)
            report = json.loads(report_path.read_text())
            self.assertEqual(git(child, "rev-list", "--count", "HEAD").strip(), "2")
            self.assertEqual(report["commands"][0]["exit_code"], 0)
            self.assertTrue(report["stale_source"])
            self.assertEqual(result, 1)

    def test_unstaged_gitlink_file_replacement_binds_working_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = indexed_gitlink(root)
            module.write_text("replacement A")
            index = git(root, "ls-files", "--stage")
            before = gate.snapshot_identity(root)
            module.write_text("replacement B")
            after = gate.snapshot_identity(root)
            self.assertTrue(index.startswith("160000 "))
            self.assertEqual(index, git(root, "ls-files", "--stage"))
            self.assertNotEqual(before["snapshot_digest"], after["snapshot_digest"])

    def test_unstaged_gitlink_symlink_replacement_binds_target_without_following(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            module = indexed_gitlink(root)
            target = Path(outside)
            (target / "private.txt").write_text("outside A")
            module.symlink_to(target, target_is_directory=True)
            before = gate.snapshot_identity(root)
            (target / "private.txt").write_text("outside B")
            self.assertEqual(before, gate.snapshot_identity(root))
            module.unlink()
            module.symlink_to(root, target_is_directory=True)
            self.assertNotEqual(before["snapshot_digest"], gate.snapshot_identity(root)["snapshot_digest"])

    def test_unstaged_gitlink_directory_replacement_binds_visible_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = indexed_gitlink(root)
            (root / ".gitignore").write_text(".env\n")
            module.mkdir()
            (module / "source.txt").write_text("source A")
            (module / ".env").write_text("ignored A")
            before = gate.snapshot_identity(root)
            (module / ".env").write_text("ignored B")
            self.assertEqual(before, gate.snapshot_identity(root))
            (module / "source.txt").write_text("source B")
            self.assertNotEqual(before["snapshot_digest"], gate.snapshot_identity(root)["snapshot_digest"])

    def test_unstaged_gitlink_replacement_mutations_during_completion_mark_source_stale(self):
        for kind in ("file", "directory", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
                root = Path(tmp)
                module = indexed_gitlink(root)
                if kind == "directory":
                    module.mkdir()
                    (module / "source.txt").write_text("before")
                    mutation = "Path('module/source.txt').write_text('after')"
                elif kind == "symlink":
                    module.symlink_to("before")
                    mutation = "Path('module').unlink(); Path('module').symlink_to('after')"
                else:
                    module.write_text("before")
                    mutation = "Path('module').write_text('after')"
                report_path = Path(state).resolve() / "report.json"
                command = gate.CommandSpec("fixture", "mutates", (sys.executable, "-c", "from pathlib import Path; " + mutation))
                result = gate.execute_plan(root, [command], "manifest", 1, mode="completion", report_path=report_path)
                report = json.loads(report_path.read_text())
                self.assertEqual(report["commands"][0]["exit_code"], 0)
                self.assertTrue(report["stale_source"])
                self.assertEqual(result, 1)

    def test_changed_paths_keeps_gitlink_symlink_and_whitespace_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = indexed_gitlink(root)
            staged = root / "staged name.txt"
            unstaged = root / "unstaged\tname.txt"
            staged.write_text("baseline")
            unstaged.write_text("baseline")
            git(root, "add", "--", staged.name, unstaged.name)
            git(root, "commit", "-qm", "tracked neighboring files")
            module.symlink_to("replacement target")
            staged.write_text("staged change")
            git(root, "add", "--", staged.name)
            unstaged.write_text("unstaged change")
            self.assertEqual(set(gate.changed_paths(root)), {"module", staged.name, unstaged.name})
            self.assertTrue(gate.snapshot_identity(root)["dirty"])

    def test_gitlink_replacement_directory_pathspec_characters_are_literal(self):
        for name in ("module[1]", "literal*module", ":(literal)module", ":(exclude)**"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                module = indexed_gitlink(root, name)
                module.mkdir()
                (module / "source.txt").write_text("source A")
                before = gate.snapshot_identity(root)
                (module / "source.txt").write_text("source B")
                self.assertNotEqual(before["snapshot_digest"], gate.snapshot_identity(root)["snapshot_digest"])

    def test_gitlink_replacement_with_present_malformed_git_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = indexed_gitlink(root)
            module.mkdir()
            (module / "source.txt").write_text("replacement")
            (module / ".git").write_text("invalid Git metadata\n")
            with self.assertRaisesRegex(gate.ManifestError, "Git|git"):
                gate.snapshot_identity(root)

    def replaced_tracked_directory(self, root, *, gitlink=False):
        initialize(root)
        directory = root / 'd'; directory.mkdir()
        (directory / 'file').write_text('original tracked source')
        git(root, 'add', 'd/file')
        if gitlink:
            module = directory / 'module'; module.mkdir()
            initialize(module)
            (module / 'source.txt').write_text('original nested source')
            git(module, 'add', '.')
            git(module, 'commit', '-qm', 'nested source')
            revision = git(module, 'rev-parse', 'HEAD').strip()
            git(root, 'update-index', '--add', '--cacheinfo', '160000,' + revision + ',d/module')
        git(root, 'commit', '-qm', 'tracked directory before symlink replacement')
        shutil.rmtree(directory)
        return directory

    def test_unstaged_tracked_directory_symlink_binds_link_without_external_descendants(self):
        for gitlink in (False, True):
            with self.subTest(gitlink=gitlink), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
                root = Path(tmp).resolve(); external = Path(outside).resolve()
                directory = self.replaced_tracked_directory(root, gitlink=gitlink)
                first = external / 'first'; first.mkdir()
                second = external / 'second'; second.mkdir()
                (first / 'file').write_text('outside content before')
                # A formerly indexed gitlink must not cause Git discovery through d.
                (first / 'module').mkdir()
                (first / 'module/.git').write_text('malformed external metadata must never be read')
                directory.symlink_to(first, target_is_directory=True)
                index = git(root, 'ls-files', '--stage')
                before = gate.snapshot_identity(root)
                (first / 'file').write_text('outside content after')
                (first / 'module/.git').write_text('different external metadata')
                self.assertEqual(before, gate.snapshot_identity(root))
                directory.unlink(); directory.symlink_to(second, target_is_directory=True)
                after = gate.snapshot_identity(root)
                self.assertNotEqual(before['snapshot_digest'], after['snapshot_digest'])
                self.assertEqual(before['revision'], after['revision'])
                self.assertEqual(index, git(root, 'ls-files', '--stage'))
                self.assertTrue(after['dirty'])

    def test_tracked_directory_symlink_mutation_during_completion_runs_and_marks_stale(self):
        for gitlink in (False, True):
            with self.subTest(gitlink=gitlink), tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
                root = Path(tmp).resolve(); external = Path(outside).resolve()
                directory = self.replaced_tracked_directory(root, gitlink=gitlink)
                first = external / 'first'; first.mkdir()
                second = external / 'second'; second.mkdir()
                directory.symlink_to(first, target_is_directory=True)
                command = gate.CommandSpec('fixture', 'retarget-link', (
                    sys.executable, '-c',
                    "import os, sys; os.unlink('d'); os.symlink(sys.argv[1], 'd', target_is_directory=True)", str(second)))
                report_path = external / 'report.json'
                result = gate.execute_plan(root, [command], 'manifest', 1, mode='completion', report_path=report_path)
                report = json.loads(report_path.read_text())
                self.assertEqual(os.readlink(directory), str(second))
                self.assertEqual(report['commands'][0]['exit_code'], 0)
                self.assertFalse(report['commands'][0]['cached'])
                self.assertTrue(report['stale_source'])
                self.assertNotEqual(report['source_before']['snapshot_digest'], report['source_after']['snapshot_digest'])
                self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
