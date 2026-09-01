import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "strict-mode" / "bin" / "strict_evidence.py"
SPEC = importlib.util.spec_from_file_location("strict_evidence", MODULE_PATH)
strict_evidence = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(strict_evidence)


class StrictEvidenceTests(unittest.TestCase):
    def test_write_is_atomic_and_index_is_generated_from_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = {
                "id": "change-001",
                "decision": "ADR-0001",
                "lane": "scoped-behavior",
                "status": "verified",
                "tests": ["python3 -m unittest"],
                "review": "https://example.invalid/pr/1",
            }
            path = strict_evidence.write_record(root, record)
            self.assertEqual(json.loads(path.read_text()), record)
            index = strict_evidence.generate_index(root)
            text = index.read_text()
            self.assertIn("change-001", text)
            self.assertIn("ADR-0001", text)
            self.assertNotIn("python3 -m unittest", text)

    def test_rejects_missing_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(strict_evidence.EvidenceError):
                strict_evidence.write_record(Path(tmp), {"id": "x"})


if __name__ == "__main__":
    unittest.main()
