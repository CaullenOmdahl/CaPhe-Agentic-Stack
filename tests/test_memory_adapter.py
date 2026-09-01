import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "memory" / "mempalace_adapter.py"
SPEC = importlib.util.spec_from_file_location("mempalace_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


class MemoryAdapterTests(unittest.TestCase):
    def test_full_turn_is_sanitized_before_chunking(self):
        secret = "ghp_" + "A" * 40
        text = "prefix " + ("x" * 30) + secret + ("y" * 30)
        chunks = adapter.sanitize_and_chunk(text, chunk_chars=32)
        combined = "".join(chunk.text for chunk in chunks)
        self.assertNotIn(secret, combined)
        self.assertIn("[REDACTED:GITHUB_TOKEN]", combined)

    def test_scope_requires_trusted_single_domain_metadata(self):
        mappings = {"project-a": "/work/a", "project-b": "/work/b"}
        self.assertEqual(adapter.resolve_scope("/work/a/src", "/work/a", mappings), "project-a")
        self.assertIsNone(adapter.resolve_scope("/work/a", "/work/b", mappings))
        self.assertIsNone(adapter.resolve_scope(None, None, mappings))

    def test_tool_output_and_untrusted_external_content_are_excluded(self):
        events = [
            {"type": "turn_context", "payload": {"cwd": "/work/a"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "secret output"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
        ]
        records, quarantined = adapter.extract_records(events, {"project-a": "/work/a"})
        self.assertEqual([record.text for record in records], ["question", "answer"])
        self.assertFalse(quarantined)
        self.assertNotIn("secret output", " ".join(record.text for record in records))

    def test_multiple_assistant_messages_in_one_trusted_turn_are_retained(self):
        events = [
            {"type": "turn_context", "payload": {"cwd": "/work/a"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "question"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "progress"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "answer"}},
        ]
        records, quarantined = adapter.extract_records(events, {"project-a": "/work/a"})
        self.assertEqual([record.text for record in records], ["question", "progress", "answer"])
        self.assertFalse(quarantined)

    def test_exact_source_resolution_returns_only_sanitized_untrusted_frame(self):
        secret = "Bearer " + "sensitive-token-value-1234567890"
        source = "before\n" + secret + "\nafter\n"
        resolved = adapter.resolve_excerpt(source, 0, len(source), source_id="session-1")
        self.assertNotIn("sensitive-token-value", resolved.text)
        self.assertIn("UNTRUSTED_MEMORY_EVIDENCE", resolved.framed)
        self.assertIn("session-1", resolved.framed)

    def test_palace_path_must_be_outside_git_and_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            inside = repo / "palace"
            inside.mkdir(mode=0o700)
            with self.assertRaises(adapter.IsolationError):
                adapter.validate_palace_path(inside)
            outside = root / "palace"
            outside.mkdir(mode=0o700)
            adapter.validate_palace_path(outside)
            outside.chmod(0o755)
            with self.assertRaises(adapter.IsolationError):
                adapter.validate_palace_path(outside)

    def test_palace_tree_audit_and_hardening_cover_generated_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "palace"
            generated = root / "generated"
            generated.mkdir(parents=True, mode=0o755)
            index = generated / "index.bin"
            index.write_bytes(b"derived")
            index.chmod(0o644)
            offenders = adapter.audit_owner_only_tree(root)
            self.assertEqual({item[0] for item in offenders}, {".", "generated", "generated/index.bin"})
            adapter.harden_owner_only_tree(root)
            self.assertEqual(adapter.audit_owner_only_tree(root), [])
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(generated.stat().st_mode & 0o777, 0o700)
            self.assertEqual(index.stat().st_mode & 0o777, 0o600)

    def test_index_identity_changes_with_sanitizer_or_embedder(self):
        first = adapter.index_generation_id("3.9.0", "chroma", "minilm", 384, "sanitize-v1", "chunk-v1")
        second = adapter.index_generation_id("3.9.0", "chroma", "minilm", 384, "sanitize-v2", "chunk-v1")
        self.assertNotEqual(first, second)

    def test_adoption_requires_pareto_improvement_and_safety(self):
        baseline = {"correct": 9, "total": 10, "recall_at_5": 0.8, "tokens": 1000}
        equal_but_leaner = {"correct": 9, "total": 10, "recall_at_5": 0.8, "tokens": 690,
                            "citations_resolved": True, "secret_canaries": 0,
                            "cross_domain_hits": 0, "injection_failures": 0}
        self.assertTrue(adapter.adoption_passes(baseline, equal_but_leaner))
        equal_and_not_leaner = dict(equal_but_leaner, tokens=800)
        self.assertFalse(adapter.adoption_passes(baseline, equal_and_not_leaner))
        unsafe = dict(equal_but_leaner, secret_canaries=1)
        self.assertFalse(adapter.adoption_passes(baseline, unsafe))


if __name__ == "__main__":
    unittest.main()
