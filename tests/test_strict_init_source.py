from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).parents[1]


class StrictInitSourceTests(unittest.TestCase):
    def test_initializer_regression_suite(self):
        script = ROOT / "strict-mode" / "test" / "strict-init-refresh-test.sh"
        result = subprocess.run([str(script)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
