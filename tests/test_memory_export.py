import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


MEMORY_DIR = Path(__file__).parents[1] / "memory"
sys.path.insert(0, str(MEMORY_DIR))
SPEC = importlib.util.spec_from_file_location("export_codex_memory", MEMORY_DIR / "export_codex_memory.py")
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(exporter)


class MemoryExportTests(unittest.TestCase):
    def test_export_is_sanitized_scoped_and_path_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            token = "ghp_" + "B" * 40
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question " + token}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            session = source / "rollout-private-name.jsonl"
            session.write_text("".join(json.dumps(event) + "\n" for event in events))
            stats = exporter.export_sources(
                [source], {"project": "/workspace/project"}, output, "generation-1"
            )
            self.assertEqual(stats["records"], 2)
            exported = next((output / "project" / "export").glob("*.md"))
            text = exported.read_text()
            self.assertNotIn(token, text)
            self.assertNotIn("rollout-private-name", text)
            self.assertIn("[REDACTED:GITHUB_TOKEN]", text)
            self.assertEqual(exported.stat().st_mode & 0o077, 0)

    def test_unmapped_session_is_quarantined_without_content_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/unknown"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "private"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            (source / "rollout.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
            stats = exporter.export_sources([source], {"project": "/workspace/project"}, output, "g")
            self.assertEqual(stats["records"], 0)
            self.assertEqual(stats["quarantined"], 1)
            self.assertFalse(any(output.rglob("*.md")))

    def test_large_session_is_partitioned_before_mining(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            events = [{"type": "turn_context", "payload": {"cwd": "/workspace/project"}}]
            for turn in range(8):
                events.extend(
                    [
                        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": f"question-{turn}-" + "x" * 40}},
                        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": f"answer-{turn}-" + "y" * 40}},
                        {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                    ]
                )
            (source / "large.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
            stats = exporter.export_sources(
                [source],
                {"project": "/workspace/project"},
                output,
                "generation-1",
                max_export_chars=240,
            )
            parts = sorted((output / "project" / "export").glob("*.md"))
            self.assertGreater(len(parts), 1)
            self.assertEqual(stats["records"], 16)
            self.assertEqual(stats["export_files"], len(parts))
            self.assertTrue(all("source_part:" in part.read_text() for part in parts))

    def test_reexport_removes_stale_partitions_for_same_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            session = source / "changing.jsonl"
            many = [{"type": "turn_context", "payload": {"cwd": "/workspace/project"}}]
            for turn in range(8):
                many.extend(
                    [
                        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": f"question-{turn}-" + "x" * 40}},
                        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": f"answer-{turn}-" + "y" * 40}},
                        {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                    ]
                )
            session.write_text("".join(json.dumps(event) + "\n" for event in many))
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "g", max_export_chars=240)
            export_dir = output / "project" / "export"
            self.assertGreater(len(list(export_dir.glob("*-p*.md"))), 1)

            few = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            session.write_text("".join(json.dumps(event) + "\n" for event in few))
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "g", max_export_chars=240)
            self.assertEqual(len(list(export_dir.glob("*.md"))), 1)
            self.assertFalse(any(export_dir.glob("*-p*.md")))


if __name__ == "__main__":
    unittest.main()
