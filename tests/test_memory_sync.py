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
                    palace = Path(command[command.index("--palace") + 1])
                    generated = palace / "index.bin"
                    generated.parent.mkdir(parents=True, exist_ok=True)
                    generated.write_bytes(b"derived")
                    generated.chmod(0o644)

            module.sync_domain(domain, generation="generation-1", runner=fake_run)
            flattened = [argument for command, _ in calls for argument in command]
            self.assertIn("--no-llm", flattened)
            self.assertIn("--max-chunks-per-file", flattened)
            self.assertIn("500", flattened)
            self.assertIn("sync", flattened)
            self.assertIn("--apply", flattened)
            self.assertNotIn("--accept-external-llm", flattened)
            self.assertTrue(all(kwargs["check"] for _, kwargs in calls))
            self.assertEqual(module.audit_owner_only_tree(domain), [])
            self.assertEqual((domain / "active-generation").read_text().strip(), "generation-1")

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
                module.sync_domain(domain, generation="generation-1", runner=failing_run)
            self.assertEqual(module.audit_owner_only_tree(domain), [])

    def test_failed_new_generation_does_not_replace_active_generation(self):
        spec = importlib.util.spec_from_file_location("sync_mempalace_generation", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "project-12345678"
            export = domain / "export"
            export.mkdir(parents=True, mode=0o700)
            (export / "source.md").write_text("sanitized source")

            def success(command, **kwargs):
                return None

            module.sync_domain(domain, generation="generation-1", runner=success)

            def failure(command, **kwargs):
                if "mine" in command:
                    raise subprocess.CalledProcessError(1, command)

            with self.assertRaises(subprocess.CalledProcessError):
                module.sync_domain(domain, generation="generation-2", runner=failure)
            self.assertEqual((domain / "active-generation").read_text().strip(), "generation-1")
            self.assertTrue((domain / "palaces" / "generation-1").is_dir())
            self.assertTrue((domain / "palaces" / "generation-2").is_dir())

    def test_empty_export_reconciles_the_active_palace(self):
        spec = importlib.util.spec_from_file_location("sync_mempalace_empty", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "project-12345678"
            (domain / "export").mkdir(parents=True, mode=0o700)
            palace = domain / "palaces" / "generation-1"
            palace.mkdir(parents=True, mode=0o700)
            (palace / ".initialized").write_text("generation-1\n")
            (domain / "active-generation").write_text("generation-1\n")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)

            module.sync_domain(domain, generation="generation-2", runner=fake_run)
            self.assertEqual(len(calls), 1)
            self.assertIn("sync", calls[0])
            self.assertNotIn("mine", calls[0])
            self.assertEqual(
                calls[0][calls[0].index("--palace") + 1], str(palace.resolve())
            )
            self.assertEqual((domain / "active-generation").read_text().strip(), "generation-1")

    def test_empty_export_reconciles_every_retained_generation(self):
        spec = importlib.util.spec_from_file_location("sync_mempalace_all_empty", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "project-12345678"
            (domain / "export").mkdir(parents=True, mode=0o700)
            palaces = []
            for generation in ("generation-1", "generation-2"):
                palace = domain / "palaces" / generation
                palace.mkdir(parents=True, mode=0o700)
                (palace / ".initialized").write_text(generation + "\n")
                palaces.append(palace.resolve())
            (domain / "active-generation").write_text("generation-2\n")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)

            module.sync_domain(domain, generation="generation-3", runner=fake_run)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("sync" in command for command in calls))
            self.assertTrue(all("mine" not in command for command in calls))
            self.assertEqual(
                {
                    Path(command[command.index("--palace") + 1])
                    for command in calls
                },
                set(palaces),
            )

    def test_empty_export_reconciles_retained_generation_without_active_pointer(self):
        spec = importlib.util.spec_from_file_location("sync_mempalace_no_pointer", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            domain = Path(tmp) / "project-12345678"
            (domain / "export").mkdir(parents=True, mode=0o700)
            palace = domain / "palaces" / "generation-1"
            palace.mkdir(parents=True, mode=0o700)
            (palace / ".initialized").write_text("generation-1\n")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)

            module.sync_domain(domain, generation="generation-2", runner=fake_run)
            self.assertEqual(len(calls), 1)
            self.assertIn("sync", calls[0])
            self.assertEqual(
                calls[0][calls[0].index("--palace") + 1], str(palace.resolve())
            )


if __name__ == "__main__":
    unittest.main()
