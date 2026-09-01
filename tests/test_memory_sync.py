import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest


MODULE_PATH = Path(__file__).parents[1] / "memory" / "sync_mempalace.py"


class MemorySyncTests(unittest.TestCase):
    def test_domain_sync_is_local_bounded_and_rehardens_generated_files(self):
        spec = importlib.util.spec_from_file_location("sync_mempalace", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "project-12345678"
            export = domain / "export"
            export.mkdir(parents=True, mode=0o700)
            (export / "source.md").write_text("sanitized source")
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                if "init" in command:
                    (export / "mempalace.yaml").write_text("backend: chroma")
                if "mine" in command:
                    generated = domain / "palace" / "index.bin"
                    generated.parent.mkdir(parents=True, exist_ok=True)
                    generated.write_bytes(b"derived")
                    generated.chmod(0o644)

            module.sync_domain(domain, runner=fake_run)
            flattened = [argument for command, _ in calls for argument in command]
            self.assertIn("--no-llm", flattened)
            self.assertIn("--max-chunks-per-file", flattened)
            self.assertIn("500", flattened)
            self.assertIn("sync", flattened)
            self.assertIn("--apply", flattened)
            self.assertNotIn("--accept-external-llm", flattened)
            self.assertTrue(all(kwargs["check"] for _, kwargs in calls))
            self.assertEqual(module.audit_owner_only_tree(domain), [])

    def test_failed_write_is_rehardened_before_error_propagates(self):
        spec = importlib.util.spec_from_file_location("sync_mempalace_failure", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "project-12345678"
            export = domain / "export"
            export.mkdir(parents=True, mode=0o700)
            (export / "source.md").write_text("sanitized source")

            def failing_run(command, **kwargs):
                generated = domain / "palace" / "partial.bin"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_bytes(b"partial")
                generated.chmod(0o644)
                raise subprocess.CalledProcessError(1, command)

            with self.assertRaises(subprocess.CalledProcessError):
                module.sync_domain(domain, runner=failing_run)
            self.assertEqual(module.audit_owner_only_tree(domain), [])


if __name__ == "__main__":
    unittest.main()
