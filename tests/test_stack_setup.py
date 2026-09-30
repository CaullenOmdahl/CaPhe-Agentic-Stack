import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "tools" / "stack_setup.py"
SPEC = importlib.util.spec_from_file_location("stack_setup", MODULE_PATH)
setup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = setup
SPEC.loader.exec_module(setup)


class FakeGh:
    """Scripted runner: maps a command prefix to (returncode, output) and records calls."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        for prefix, result in self.responses:
            if cmd[:len(prefix)] == prefix:
                return result(cmd) if callable(result) else result
        return 1, "unexpected: " + " ".join(cmd)


def user(tfa=True):
    return (0, json.dumps({"login": "owner", "two_factor_authentication": tfa}))


class HomeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve()
        self.patches = [mock.patch.object(setup, "home", return_value=self.home),
                        mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home / "state")})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()


class ClientTests(HomeTest):
    def test_detects_any_subset_by_binary_or_config_dir(self):
        (self.home / ".claude").mkdir()
        found = setup.detect_clients(which=lambda cmd: "/bin/codex" if cmd == "codex" else None)
        self.assertEqual(sorted(found), ["claude", "codex"])

    def test_wiring_is_idempotent_and_preserves_existing_text(self):
        entry = self.home / ".codex" / "AGENTS.md"
        entry.parent.mkdir()
        entry.write_text("# Mine\n\nkeep me\n")
        clients = {"codex": {}}
        first = setup.wire_clients(clients, self.home / "agent-memory", self.home / "rt")
        second = setup.wire_clients(clients, self.home / "agent-memory", self.home / "rt")
        text = entry.read_text()
        self.assertEqual((first["codex"], second["codex"]), ("updated", "current"))
        self.assertIn("keep me", text)
        self.assertEqual(text.count(setup.BEGIN), 1)
        self.assertIn("update-check", text)

    def test_claude_block_imports_global_index(self):
        setup.wire_clients({"claude": {}}, self.home / "hub", None)
        self.assertIn(f"@{self.home / 'hub' / 'global' / 'MEMORY.md'}",
                      (self.home / ".claude" / "CLAUDE.md").read_text())

    def test_opencode_instruction_added_once_and_jsonc_left_alone(self):
        cfg = self.home / ".config" / "opencode" / "opencode.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"instructions": ["a.md"]}))
        r1 = setup.wire_clients({"opencode": {}}, self.home / "hub", None)
        r2 = setup.wire_clients({"opencode": {}}, self.home / "hub", None)
        self.assertIn("instructions added", r1["opencode"])
        self.assertIn("instructions present", r2["opencode"])
        self.assertEqual(len(json.loads(cfg.read_text())["instructions"]), 2)
        cfg.write_text('{ // comment\n "instructions": [] }')
        self.assertIn("manual", setup.wire_clients({"opencode": {}}, self.home / "hub", None)["opencode"])


class NoClaudeMachineTests(HomeTest):
    def test_memory_hub_setup_works_without_claude_and_never_creates_claude_config(self):
        (self.home / ".codex").mkdir()
        (self.home / ".config" / "opencode").mkdir(parents=True)
        (self.home / ".config" / "opencode" / "opencode.json").write_text("{}")
        dest = self.home / "agent-memory"
        (dest / ".git").mkdir(parents=True)
        gh = FakeGh([(["gh", "api", "user"], user()), (["gh", "repo", "view"], (0, "PRIVATE\n")),
                     (["git", "-C", str(dest), "remote"], (0, "https://github.com/owner/agent-memory.git\n")),
                     (["git", "-C", str(dest), "pull"], (0, "")), (["git"], (0, ""))])
        with mock.patch.object(setup.shutil, "which", lambda cmd: None):
            rc = setup.main(["memory-hub", "--dest", str(dest), "--runtime", str(self.home / "rt")], run=gh)
        self.assertEqual(rc, 0)
        self.assertIn(setup.BEGIN, (self.home / ".codex" / "AGENTS.md").read_text())
        self.assertIn(setup.BEGIN, (self.home / ".config" / "opencode" / "AGENTS.md").read_text())
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".gemini").exists())


class OpenCodePermissionTests(HomeTest):
    def test_memory_stores_readable_without_prompts_and_existing_rules_kept(self):
        cfg = self.home / ".config" / "opencode" / "opencode.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"permission": {"external_directory": "ask", "bash": {"*": "allow"}}}))
        setup.wire_clients({"opencode": {}}, self.home / "hub", None)
        data = json.loads(cfg.read_text())
        rules = data["permission"]["external_directory"]
        self.assertEqual(rules["*"], "ask")  # previous blanket rule becomes the default
        self.assertEqual(rules[f"{self.home / 'hub'}/*"], "allow")
        self.assertEqual(rules["*/.agent/memory/*"], "allow")
        self.assertEqual(data["permission"]["bash"], {"*": "allow"})
        setup.wire_clients({"opencode": {}}, self.home / "hub", None)
        self.assertEqual(json.loads(cfg.read_text()), data)  # idempotent


class HubTests(HomeTest):
    def test_refuses_without_2fa(self):
        with self.assertRaisesRegex(setup.SetupError, "two-factor"):
            setup.ensure_hub(FakeGh([(["gh", "api", "user"], user(False))]), self.home / "h", "agent-memory", None, False)

    def test_unverifiable_2fa_needs_explicit_flag(self):
        gh = FakeGh([(["gh", "api", "user"], user(None))])
        with self.assertRaisesRegex(setup.SetupError, "allow-unverified-2fa"):
            setup.ensure_hub(gh, self.home / "h", "agent-memory", None, False)

    def test_refuses_public_hub(self):
        gh = FakeGh([(["gh", "api", "user"], user()), (["gh", "repo", "view"], (0, "PUBLIC\n"))])
        with self.assertRaisesRegex(setup.SetupError, "must be PRIVATE"):
            setup.ensure_hub(gh, self.home / "h", "agent-memory", None, False)

    def test_missing_hub_is_recommended_not_created_without_flag(self):
        gh = FakeGh([(["gh", "api", "user"], user()), (["gh", "repo", "view"], (1, "not found"))])
        with self.assertRaisesRegex(setup.SetupError, "PRIVATE repository"):
            setup.ensure_hub(gh, self.home / "h", "agent-memory", None, False)
        self.assertFalse(any(c[:3] == ["gh", "repo", "create"] for c in gh.calls))

    def test_create_makes_private_repo_clones_scaffolds_and_pushes(self):
        views = iter([(1, "not found"), (0, "PRIVATE\n")])
        dest = self.home / "agent-memory"

        def clone(cmd):
            Path(cmd[-1]).mkdir(parents=True)
            return 0, ""

        gh = FakeGh([(["gh", "api", "user"], user()), (["gh", "repo", "view"], lambda c: next(views)),
                     (["gh", "repo", "create"], (0, "")), (["gh", "repo", "clone"], clone),
                     (["git"], (0, ""))])
        result = setup.ensure_hub(gh, dest, "agent-memory", None, True)
        create = next(c for c in gh.calls if c[:3] == ["gh", "repo", "create"])
        self.assertIn("--private", create)
        self.assertTrue((dest / "projects.json").is_file())
        self.assertTrue(any("push" in c and "-u" in c for c in gh.calls))
        self.assertTrue(result["action"].startswith("created"))

    def test_existing_empty_hub_gets_scaffold_committed_and_pushed(self):
        dest = self.home / "agent-memory"

        def clone(cmd):
            Path(cmd[-1]).mkdir(parents=True)
            return 0, ""

        gh = FakeGh([(["gh", "api", "user"], user()), (["gh", "repo", "view"], (0, "PRIVATE\n")),
                     (["gh", "repo", "clone"], clone), (["git"], (0, ""))])
        setup.ensure_hub(gh, dest, "agent-memory", None, False)
        self.assertTrue(any("push" in c for c in gh.calls))

    def test_opencode_string_instructions_are_kept_and_extended(self):
        cfg = self.home / ".config" / "opencode" / "opencode.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"instructions": "mine.md"}))
        setup.wire_clients({"opencode": {}}, self.home / "hub", None)
        self.assertEqual(json.loads(cfg.read_text())["instructions"][0], "mine.md")
        cfg.write_text(json.dumps({"instructions": None}))
        setup.wire_clients({"opencode": {}}, self.home / "hub", None)
        self.assertEqual(len(json.loads(cfg.read_text())["instructions"]), 1)

    def test_existing_clone_fast_forwards_and_rejects_foreign_remote(self):
        dest = self.home / "agent-memory"
        (dest / ".git").mkdir(parents=True)
        base = [(["gh", "api", "user"], user()), (["gh", "repo", "view"], (0, "PRIVATE\n"))]
        ok = FakeGh(base + [(["git", "-C", str(dest), "remote"], (0, "git@github.com:owner/agent-memory.git\n")),
                            (["git", "-C", str(dest), "pull"], (0, "")), (["git"], (0, ""))])
        self.assertEqual(setup.ensure_hub(ok, dest, "agent-memory", None, False)["action"], "fast-forwarded")
        bad = FakeGh(base + [(["git", "-C", str(dest), "remote"], (0, "https://github.com/else/thing.git\n"))])
        with self.assertRaisesRegex(setup.SetupError, "not a clone"):
            setup.ensure_hub(bad, dest, "agent-memory", None, False)


class ReviewRouteTests(HomeTest):
    def test_lists_installed_reviewers_with_independence_and_model_config(self):
        conf = self.home / ".config" / "caphe" / "review-models.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text("STRICT_CONFER_CLAUDE_MODEL=m1\n")
        which = {"claude": "/bin/claude", "codex": "/bin/codex", "gh": "/bin/gh"}.get
        run = FakeGh([(["/bin/claude", "--version"], (0, "2.1 (Claude Code)\n")),
                      (["/bin/codex", "--version"], (0, "codex-cli 0.1\n")),
                      (["gh", "auth", "status"], (0, ""))])
        routes = setup.review_routes(run, which=which, current="codex")
        local = {r["reviewer"]: r for r in routes["local"]}
        self.assertEqual(sorted(local), ["claude", "codex"])
        self.assertTrue(local["claude"]["independent"])
        self.assertFalse(local["codex"]["independent"])
        self.assertEqual(local["claude"]["model"], "m1")
        self.assertIsNone(local["codex"]["model"])
        self.assertTrue(routes["remote"]["gh_authenticated"])

    def test_no_reviewers_installed_is_reported_not_raised(self):
        routes = setup.review_routes(FakeGh([]), which=lambda c: None, current="claude")
        self.assertEqual(routes["local"], [])
        self.assertFalse(routes["remote"]["gh_authenticated"])


class UpdateCheckTests(HomeTest):
    NOW = dt.datetime(2026, 9, 30, 12, tzinfo=dt.timezone.utc)

    def test_rate_limited_and_state_outside_git(self):
        gh = FakeGh([(["git", "ls-remote"], (0, "abc123\trefs/heads/main\n"))])
        first = setup.update_check(gh, self.NOW, dt.timedelta(days=2), False)
        second = setup.update_check(gh, self.NOW + dt.timedelta(hours=5), dt.timedelta(days=2), False)
        third = setup.update_check(gh, self.NOW + dt.timedelta(days=3), dt.timedelta(days=2), False)
        self.assertEqual([first["checked"], second["checked"], third["checked"]], [True, False, True])
        self.assertEqual(len(gh.calls), 2)
        self.assertTrue((self.home / "state" / "caphe" / "update-check.json").is_file())

    def test_update_available_until_marked_applied(self):
        gh = FakeGh([(["git", "ls-remote"], (0, "abc123\trefs/heads/main\n"))])
        self.assertTrue(setup.update_check(gh, self.NOW, dt.timedelta(days=2), True)["update_available"])
        setup.mark_applied(None)
        self.assertFalse(setup.update_check(gh, self.NOW, dt.timedelta(days=2), True)["update_available"])

    def test_unreachable_remote_reports_and_does_not_record_a_check(self):
        gh = FakeGh([(["git", "ls-remote"], (128, "fatal"))])
        with self.assertRaises(setup.SetupError):
            setup.update_check(gh, self.NOW, dt.timedelta(days=2), False)
        self.assertFalse((self.home / "state" / "caphe" / "update-check.json").exists())


if __name__ == "__main__":
    unittest.main()
