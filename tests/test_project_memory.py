import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "memory" / "project_memory.py"
SPEC = importlib.util.spec_from_file_location("project_memory", MODULE_PATH)
pm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pm  # dataclasses resolve deferred annotations via sys.modules
SPEC.loader.exec_module(pm)


GOOD = """---
name: No parallel builds
description: Never run two heavy builds at once; memory exhaustion crashes the machine
type: feedback
created: 2026-03-23
updated: 2026-03-23
source: claude
status: active
---

Run builds one at a time.
"""


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class TempTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.hub = pm.Hub(self.tmp / "hub")

    def tearDown(self):
        self._tmp.cleanup()

    def make_repo(self, rel):
        root = self.tmp / rel
        root.mkdir(parents=True, exist_ok=True)
        git("init", "-q", cwd=root)
        git("config", "user.email", "t@example.invalid", cwd=root)
        git("config", "user.name", "t", cwd=root)
        (root / pm.STORE_REL).mkdir(parents=True)
        return root

    def write(self, store, name, text=GOOD):
        store.mkdir(parents=True, exist_ok=True)
        (store / name).write_text(text)
        return store / name


class FormatTests(TempTree):
    def test_parse_valid_memory(self):
        m = pm.parse_memory(self.write(self.tmp / "s", "feedback_x.md"))
        self.assertEqual(m.type, "feedback")
        self.assertEqual(m.status, "active")
        self.assertIn("one at a time", m.body)

    def test_check_flags_missing_field(self):
        store = self.tmp / "s"
        self.write(store, "project_x.md", GOOD.replace("type: feedback\n", ""))
        problems = pm.check_store(store, include_index=False)
        self.assertTrue(any("type" in p.message for p in problems))

    def test_check_flags_bad_enum_and_date(self):
        store = self.tmp / "s"
        self.write(store, "x.md", GOOD.replace("feedback", "misc").replace("2026-03-23", "March"))
        messages = " ".join(p.message for p in pm.check_store(store, include_index=False))
        self.assertIn("type must be one of", messages)
        self.assertIn("YYYY-MM-DD", messages)

    def test_credential_is_a_warning_with_line_number(self):
        store = self.tmp / "s"
        token = "ghp_" + "A" * 36
        self.write(store, "reference_key.md", GOOD + f"\nkey {token}\n")
        problems = [p for p in pm.check_store(store, include_index=False) if "secret" in p.message]
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].severity, "warning")
        self.assertGreater(problems[0].line, 10)

    def test_private_store_with_secret_still_indexes_and_checks_clean(self):
        store = self.tmp / "s"
        self.write(store, "reference_key.md", GOOD + "\n" + "github" + "_pat_" + "B" * 30 + "\n")
        pm.write_index(store)
        self.assertEqual(pm.errors(pm.check_store(store)), [])

    def test_fail_on_secrets_turns_warnings_into_errors_for_public_repos(self):
        store = self.tmp / "s"
        self.write(store, "reference_key.md", GOOD + "\n" + "github" + "_pat_" + "B" * 30 + "\n")
        pm.write_index(store)
        self.assertEqual(pm.main(["check", str(store)]), 0)
        self.assertEqual(pm.main(["check", "--fail-on-secrets", str(store)]), 1)

    def test_index_refuses_schema_errors(self):
        store = self.tmp / "s"
        self.write(store, "x.md", GOOD.replace("type: feedback\n", ""))
        with self.assertRaises(pm.StoreError):
            pm.write_index(store)


class NativeWriterTests(TempTree):
    CLAUDE_NATIVE = "---\nname: X\ndescription: d\nmetadata:\n  type: feedback\n---\n\nbody\n"

    def test_claude_native_file_has_no_errors_only_recommendations(self):
        store = self.tmp / "s"
        self.write(store, "feedback_x.md", self.CLAUDE_NATIVE)
        problems = pm.check_store(store, include_index=False)
        self.assertEqual(pm.errors(problems), [])
        self.assertTrue(any("recommended" in p.message for p in problems))
        pm.write_index(store)

    def test_hand_edited_index_is_a_warning(self):
        store = self.tmp / "s"
        self.write(store, "feedback_x.md")
        pm.write_index(store)
        (store / pm.INDEX).write_text("# Memory Index\n\n- hand edit\n")
        problems = pm.check_store(store)
        self.assertEqual(pm.errors(problems), [])
        self.assertTrue(any("stale" in p.message for p in problems))


class DiscoveryTests(TempTree):
    def test_nested_repo_sees_inner_then_parent_store(self):
        outer = self.make_repo("outer")
        (outer / ".gitignore").write_text("inner/\n")
        inner = self.make_repo("outer/inner")
        roots = [s.root for s in pm.stores_for(inner / pm.STORE_REL, self.hub)]
        self.assertEqual(roots[:2], [inner / pm.STORE_REL, outer / pm.STORE_REL])

    def test_linked_worktree_uses_its_own_store(self):
        repo = self.make_repo("repo")
        self.write(repo / pm.STORE_REL, "feedback_a.md")
        git("add", ".", cwd=repo)
        git("commit", "-qm", "init", cwd=repo)
        wt = self.tmp / "wt"
        git("worktree", "add", "-q", str(wt), cwd=repo)
        roots = [s.root for s in pm.stores_for(wt, self.hub)]
        self.assertEqual(roots[0], wt / pm.STORE_REL)
        self.assertTrue((roots[0] / "feedback_a.md").is_file())

    def test_hub_mapping_wins_for_write_target_and_global_is_listed(self):
        public = self.make_repo("public")
        self.hub.projects[str(public)] = "public-repo"
        (self.hub.root / "projects" / "public-repo").mkdir(parents=True)
        (self.hub.root / "global").mkdir(parents=True)
        self.assertEqual(pm.write_target(public, self.hub).kind, "hub-project")
        kinds = [s.kind for s in pm.stores_for(public, self.hub)]
        self.assertEqual(kinds[-2:], ["hub-project", "hub-global"])

    def test_non_git_unmapped_folder_goes_to_hub_by_name(self):
        folder = self.tmp / "notes"
        folder.mkdir()
        target = pm.write_target(folder, self.hub)
        self.assertEqual(target.root, self.hub.root / "projects" / "notes")


class SearchTests(TempTree):
    def test_search_covers_parent_repo_and_hub_stores(self):
        outer = self.make_repo("outer")
        (outer / ".gitignore").write_text("inner/\n")
        inner = self.make_repo("outer/inner")
        self.write(outer / pm.STORE_REL, "project_bond.md",
                   GOOD.replace("No parallel builds", "Android 15 BLE bond staleness"))
        self.write(inner / pm.STORE_REL, "feedback_other.md")
        (self.hub.root / "global").mkdir(parents=True)
        self.write(self.hub.root / "global", "user_x.md", GOOD.replace("heavy builds", "bond reviews"))
        hits = pm.search(inner, ["android", "bond"], self.hub)
        self.assertEqual([h.path.name for h in hits], ["project_bond.md"])  # all terms must match
        self.assertEqual(hits[0].store.root, outer / pm.STORE_REL)
        phrase = pm.search(inner, ["android 15 BLE bond"], self.hub)  # quoted phrase = its words
        self.assertEqual([h.path.name for h in phrase], ["project_bond.md"])
        any_hits = pm.search(inner, ["bond"], self.hub)
        self.assertEqual({h.path.name for h in any_hits}, {"project_bond.md", "user_x.md"})

    def test_search_ranks_name_and_description_matches_first_and_skips_index(self):
        repo = self.make_repo("r")
        store = repo / pm.STORE_REL
        self.write(store, "project_body.md", GOOD + "\nmentions widget in body\n")
        self.write(store, "project_title.md", GOOD.replace("No parallel builds", "Widget rules"))
        pm.write_index(store)
        names = [h.path.name for h in pm.search(repo, ["widget"], self.hub)]
        self.assertEqual(names, ["project_title.md", "project_body.md"])


class ImportTests(TempTree):
    def test_import_claude_converts_and_is_idempotent(self):
        src = self.tmp / "claude"
        self.write(src, "feedback_x.md", "---\nname: X\ndescription: d\nmetadata:\n  type: feedback\n---\n\nbody\n")
        self.write(src, "MEMORY.md", "# index\n")
        dest = self.tmp / "dest"
        first = pm.import_claude(src, dest)
        self.assertEqual(len(first), 1)
        mem = pm.parse_memory(first[0])
        self.assertEqual((mem.type, mem.status), ("feedback", "active"))
        self.assertTrue(mem.source.startswith("claude import #"))
        self.assertEqual(pm.check_store(dest, include_index=False), [])
        self.assertEqual(pm.import_claude(src, dest), [])

    def test_import_codex_routes_groups_and_rollouts_idempotently(self):
        repo = self.make_repo("proj")
        codex = self.tmp / "codex" / "memories"
        (codex / "rollout_summaries").mkdir(parents=True)
        (codex / "MEMORY.md").write_text(
            f"# Task Group: {repo} Fix the widget\n\nscope: repair widget\n\n## Reusable knowledge\n\n- use X\n")
        (codex / "rollout_summaries" / "2026-09-01T02-58-48-N9be-widget_fix.md").write_text(
            f"thread_id: t\ncwd: {repo}\n\n# Fixed the widget\n\ndetails\n")
        home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.tmp)  # codex_paths keys on the home prefix
        try:
            written = pm.import_codex(self.tmp / "codex", lambda path, subject: pm.write_target(Path(path), self.hub).root if path else None)
            again = pm.import_codex(self.tmp / "codex", lambda path, subject: pm.write_target(Path(path), self.hub).root if path else None)
        finally:
            os.environ["HOME"] = home
        names = sorted(p.name for p in written)
        self.assertEqual(len(names), 2)
        self.assertTrue(any(n.startswith("project_codex-fix-the-widget") for n in names))
        self.assertTrue(any(n.startswith("session_2026-09-01_") for n in names))
        self.assertEqual(again, [])
        self.assertEqual(pm.check_store(repo / pm.STORE_REL, include_index=False), [])

    def test_router_subject_override_and_archive(self):
        self.hub.overrides = [{"match": "RideDat", "under": str(self.tmp), "store": str(self.tmp / "ride")}]
        route = pm.make_router(self.hub)
        self.assertEqual(route(str(self.tmp / "x"), "RideDat audit"), self.tmp / "ride")
        self.assertEqual(route(str(self.tmp / "gone"), "other"), self.hub.root / "projects" / "_archive" / "gone")
        self.assertEqual(route("", "profile"), self.hub.root / "global")


class LinkTests(TempTree):
    def test_link_claude_replaces_migrated_dir_and_refuses_pending(self):
        repo = self.make_repo("proj")
        claude = self.tmp / "claude-home"
        slug = str(repo).replace("/", "-").replace("_", "-").replace(".", "-")
        native = claude / "projects" / slug / "memory"
        self.write(native, "feedback_x.md", "---\nname: X\ndescription: d\ntype: feedback\n---\n\nbody\n")
        with self.assertRaises(pm.StoreError):
            pm.link_claude(repo, claude)
        pm.import_claude(native, repo / pm.STORE_REL)
        link = pm.link_claude(repo, claude)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (repo / pm.STORE_REL).resolve())
        self.assertTrue(any(p.name.startswith("memory.pre-git-") for p in link.parent.iterdir()))
        self.assertEqual(pm.link_claude(repo, claude), link)  # idempotent


class CliTests(TempTree):
    def test_new_then_check_and_index(self):
        repo = self.make_repo("proj")
        os.environ["CAPHE_MEMORY_HUB"] = str(self.hub.root)
        try:
            self.assertEqual(pm.main(["new", "reference", "Test device", "Phone on wireless adb",
                                      "--path", str(repo), "--source", "codex", "--body", "adb-wifi"]), 0)
            store = repo / pm.STORE_REL
            self.assertEqual(pm.main(["index", str(store)]), 0)
            self.assertEqual(pm.main(["check", str(store)]), 0)
            self.assertEqual(pm.main(["new", "reference", "Test device", "dup", "--path", str(repo)]), 1)
        finally:
            del os.environ["CAPHE_MEMORY_HUB"]


if __name__ == "__main__":
    unittest.main()
