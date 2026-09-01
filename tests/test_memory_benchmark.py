import importlib.util
from pathlib import Path
import sys
import unittest


MEMORY_DIR = Path(__file__).parents[1] / "memory"
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))
MODULE_PATH = MEMORY_DIR / "benchmark_memory.py"
SPEC = importlib.util.spec_from_file_location("benchmark_memory", MODULE_PATH)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(benchmark)


class MemoryBenchmarkTests(unittest.TestCase):
    def test_injection_gate_is_measured_not_read_from_candidate_results(self):
        cases = [
            {
                "id": "case-1",
                "expected_source_ids": ["source-1"],
                "answer_predicates": ["fact"],
            }
        ]
        results = [
            {
                "id": "case-1",
                "source_ids": ["source-1"],
                "answer": "fact",
                "retrieved_tokens": 1,
                "citations_resolved": True,
                "injection_failures": 99,
            }
        ]
        scored = benchmark.score(cases, results)
        self.assertEqual(scored["injection_failures"], 0)
        self.assertEqual(benchmark.measure_frame_injection_failures(), 0)


if __name__ == "__main__":
    unittest.main()
