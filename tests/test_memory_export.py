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
    def test_missing_source_root_fails_before_export_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "pilot"
            output.mkdir(mode=0o700)
            sentinel = output / "sentinel"
            sentinel.write_text("unchanged")
            with self.assertRaisesRegex(ValueError, "source root"):
                exporter.export_sources(
                    [root / "missing-sessions"],
                    {"project": "/workspace/project"},
                    output,
                    "generation-1",
                )
            self.assertEqual(sentinel.read_text(), "unchanged")

    def test_symlinked_transcript_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            external = root / "external"
            output = root / "pilot"
            source.mkdir()
            external.mkdir()
            output.mkdir(mode=0o700)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {
                    "type": "response_item",
                    "payload": {"type": "message", "role": "user", "content": "outside"},
                },
            ]
            target = external / "private.jsonl"
            target.write_text("".join(json.dumps(event) + "\n" for event in events))
            (source / "linked.jsonl").symlink_to(target)

            with self.assertRaisesRegex(ValueError, "symlink|source root"):
                exporter.export_sources(
                    [source], {"project": "/workspace/project"}, output, "generation-1"
                )

            self.assertFalse(any(output.rglob("*.md")))

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
            catalog = output / "source-catalog.json"
            self.assertEqual(catalog.stat().st_mode & 0o077, 0)
            self.assertIn(str(session.resolve()), json.loads(catalog.read_text()).values())
            processed_state = output / "processed-state.json"
            self.assertEqual(processed_state.stat().st_mode & 0o077, 0)

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

    def test_source_ids_are_namespaced_by_source_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_root = root / "first"
            second_root = root / "second"
            first = first_root / "same" / "session.jsonl"
            second = second_root / "same" / "session.jsonl"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text("")
            second.write_text("")
            self.assertNotEqual(
                exporter.safe_source_id(first_root, first),
                exporter.safe_source_id(second_root, second),
            )

    def test_retired_source_root_is_pruned_from_derived_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retired = root / "retired-sessions"
            current = root / "current-sessions"
            output = root / "pilot"
            retired.mkdir()
            current.mkdir()
            output.mkdir(mode=0o700)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {
                    "type": "response_item",
                    "payload": {"type": "message", "role": "user", "content": "retire me"},
                },
                {
                    "type": "response_item",
                    "payload": {"type": "message", "role": "assistant", "content": "answer"},
                },
            ]
            source = retired / "session.jsonl"
            source.write_text("".join(json.dumps(event) + "\n" for event in events))
            exporter.export_sources(
                [retired], {"project": "/workspace/project"}, output, "generation-1"
            )
            self.assertTrue(any((output / "project" / "export").glob("*.md")))

            exporter.export_sources(
                [current], {"project": "/workspace/project"}, output, "generation-1"
            )

            self.assertFalse(any((output / "project" / "export").glob("*.md")))
            self.assertEqual(json.loads((output / "source-catalog.json").read_text()), {})
            self.assertEqual(json.loads((output / "processed-state.json").read_text()), {})

    def test_orphaned_export_without_catalog_state_is_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            export = output / "project" / "export"
            source.mkdir()
            export.mkdir(parents=True, mode=0o700)
            output.chmod(0o700)
            orphan = export / "0123456789abcdefabcd.md"
            orphan.write_text(
                "source_id: 0123456789abcdefabcd\n"
                "source_part: 1/1\n"
                f"source_sha256: {'a' * 64}\n"
                "index_generation: generation-1\n"
                "trust: first-party-conversation\n\n"
                "[user source_event=1]\ndeleted source\n"
            )

            exporter.export_sources(
                [source], {"project": "/workspace/project"}, output, "generation-1"
            )

            self.assertFalse(orphan.exists())

    def test_unsafe_domain_name_is_rejected_before_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            (source / "session.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
            with self.assertRaises(exporter.IsolationError):
                exporter.export_sources([source], {"../escaped": "/workspace/project"}, output, "g")
            self.assertFalse((root / "escaped").exists())

    def test_symlinked_domain_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            real_domain = output / "domain-b"
            real_domain.mkdir(mode=0o700)
            (output / "domain-a").symlink_to(real_domain, target_is_directory=True)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/a"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            (source / "session.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
            with self.assertRaises(exporter.IsolationError):
                exporter.export_sources([source], {"domain-a": "/workspace/a"}, output, "g")
            self.assertFalse((real_domain / "export").exists())

    def test_symlinked_export_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            outside = root / "outside"
            source.mkdir()
            output.mkdir(mode=0o700)
            outside.mkdir(mode=0o700)
            domain = output / "project"
            domain.mkdir(mode=0o700)
            (domain / "export").symlink_to(outside, target_is_directory=True)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            (source / "session.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events)
            )
            with self.assertRaises(exporter.IsolationError):
                exporter.export_sources(
                    [source], {"project": "/workspace/project"}, output, "g"
                )
            self.assertFalse(any(outside.iterdir()))

    def test_reexport_removes_source_from_previous_or_quarantined_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            session = source / "moving.jsonl"

            def write_turn(cwd):
                events = [
                    {"type": "turn_context", "payload": {"cwd": cwd}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
                ]
                session.write_text("".join(json.dumps(event) + "\n" for event in events))

            write_turn("/workspace/a")
            exporter.export_sources([source], {"domain-a": "/workspace/a"}, output, "g")
            self.assertTrue(any((output / "domain-a" / "export").glob("*.md")))
            write_turn("/workspace/b")
            exporter.export_sources([source], {"domain-b": "/workspace/b"}, output, "g")
            self.assertFalse(any((output / "domain-a" / "export").glob("*.md")))
            self.assertTrue(any((output / "domain-b" / "export").glob("*.md")))
            write_turn("/workspace/unmapped")
            exporter.export_sources([source], {"domain-b": "/workspace/b"}, output, "g")
            self.assertFalse(any((output / "domain-b" / "export").glob("*.md")))

    def test_deleted_sources_are_pruned_from_exports_and_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            session = source / "deleted.jsonl"
            session.write_text("".join(json.dumps(event) + "\n" for event in events))
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "g")
            self.assertTrue(any((output / "project" / "export").glob("*.md")))
            session.unlink()
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "g")
            self.assertFalse(any((output / "project" / "export").glob("*.md")))
            self.assertEqual(json.loads((output / "source-catalog.json").read_text()), {})

    def test_generation_transition_refuses_a_partial_export_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            for name in ("one", "two"):
                events = [
                    {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": name}},
                    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
                ]
                (source / f"{name}.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events)
                )
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "old")
            with self.assertRaises(ValueError):
                exporter.export_sources(
                    [source], {"project": "/workspace/project"}, output, "new", limit=1
                )
            self.assertTrue(
                all(
                    "index_generation: old" in path.read_text()
                    for path in (output / "project" / "export").glob("*.md")
                )
            )

    def test_generation_transition_refuses_an_invalid_source_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            valid = source / "valid.jsonl"
            invalid = source / "invalid.jsonl"

            def events(label):
                return [
                    {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": label}},
                    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
                ]

            valid.write_text("".join(json.dumps(event) + "\n" for event in events("valid")))
            invalid.write_text("".join(json.dumps(event) + "\n" for event in events("invalid")))
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "old")
            old_exports = {
                path.name: path.read_text()
                for path in (output / "project" / "export").glob("*.md")
            }
            invalid.write_text("{malformed\n")
            with self.assertRaises(ValueError):
                exporter.export_sources(
                    [source], {"project": "/workspace/project"}, output, "new"
                )
            self.assertEqual(
                {
                    path.name: path.read_text()
                    for path in (output / "project" / "export").glob("*.md")
                },
                old_exports,
            )

    def test_invalid_source_is_pruned_during_same_generation_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            session = source / "invalidated.jsonl"
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            session.write_text("".join(json.dumps(event) + "\n" for event in events))
            exporter.export_sources([source], {"project": "/workspace/project"}, output, "g")
            self.assertTrue(any((output / "project" / "export").glob("*.md")))
            session.write_text("{malformed\n")
            stats = exporter.export_sources(
                [source], {"project": "/workspace/project"}, output, "g"
            )
            self.assertEqual(stats["invalid"], 1)
            self.assertFalse(any((output / "project" / "export").glob("*.md")))
            self.assertEqual(json.loads((output / "source-catalog.json").read_text()), {})

    def test_mapping_change_requires_complete_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            for name in ("one", "two"):
                events = [
                    {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": name}},
                    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
                ]
                (source / f"{name}.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events)
                )
            exporter.export_sources(
                [source], {"old-domain": "/workspace/project"}, output, "g"
            )
            old_exports = {
                path.name: path.read_text()
                for path in (output / "old-domain" / "export").glob("*.md")
            }
            with self.assertRaises(ValueError):
                exporter.export_sources(
                    [source],
                    {"new-domain": "/workspace/project"},
                    output,
                    "g",
                    limit=1,
                )
            self.assertEqual(
                {
                    path.name: path.read_text()
                    for path in (output / "old-domain" / "export").glob("*.md")
                },
                old_exports,
            )

    def test_repeated_bounded_syncs_advance_past_completed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            for index, name in enumerate(("oldest", "middle", "newest"), 1):
                events = [
                    {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": name}},
                    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
                ]
                path = source / f"{name}.jsonl"
                path.write_text("".join(json.dumps(event) + "\n" for event in events))
                os.utime(path, (index, index))

            first = exporter.export_sources(
                [source],
                {"project": "/workspace/project"},
                output,
                "g",
                limit=2,
                recent_first=True,
            )
            second = exporter.export_sources(
                [source],
                {"project": "/workspace/project"},
                output,
                "g",
                limit=2,
                recent_first=True,
            )

            self.assertEqual(first["sessions"], 2)
            self.assertEqual(second["sessions"], 1)
            self.assertEqual(
                len(json.loads((output / "source-catalog.json").read_text())),
                3,
            )

    def test_processed_state_does_not_hide_a_missing_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)
            events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            (source / "session.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events)
            )
            exporter.export_sources(
                [source], {"project": "/workspace/project"}, output, "g"
            )
            export_path = next((output / "project" / "export").glob("*.md"))
            export_path.unlink()

            stats = exporter.export_sources(
                [source],
                {"project": "/workspace/project"},
                output,
                "g",
                limit=1,
            )

            self.assertEqual(stats["sessions"], 1)
            self.assertTrue(any((output / "project" / "export").glob("*.md")))

    def test_quarantined_and_invalid_sources_do_not_starve_a_bounded_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sessions"
            output = root / "pilot"
            source.mkdir()
            output.mkdir(mode=0o700)

            mapped_events = [
                {"type": "turn_context", "payload": {"cwd": "/workspace/project"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
            ]
            mapped = source / "mapped.jsonl"
            mapped.write_text("".join(json.dumps(event) + "\n" for event in mapped_events))
            quarantined = source / "quarantined.jsonl"
            quarantined.write_text(
                "".join(
                    json.dumps(event) + "\n"
                    for event in [
                        {"type": "turn_context", "payload": {"cwd": "/unmapped"}},
                        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "private"}},
                    ]
                )
            )
            invalid = source / "invalid.jsonl"
            invalid.write_text("{malformed\n")
            for timestamp, path in enumerate((mapped, quarantined, invalid), 1):
                os.utime(path, (timestamp, timestamp))

            first = exporter.export_sources(
                [source],
                {"project": "/workspace/project"},
                output,
                "g",
                limit=2,
                recent_first=True,
            )
            second = exporter.export_sources(
                [source],
                {"project": "/workspace/project"},
                output,
                "g",
                limit=2,
                recent_first=True,
            )

            self.assertEqual(first["sessions"], 2)
            self.assertEqual(second["sessions"], 1)
            self.assertTrue(any((output / "project" / "export").glob("*.md")))

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
