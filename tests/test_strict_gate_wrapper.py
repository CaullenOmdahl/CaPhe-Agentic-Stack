import os
from pathlib import Path
import subprocess
import tempfile
import unittest


WRAPPER = Path(__file__).parents[1] / "strict-mode/bin/strict-green-gate.sh"


class WrapperTests(unittest.TestCase):
    def invoke(self, arguments, exit_code=9):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "strict-green-gate.sh").write_bytes(WRAPPER.read_bytes())
            (root / "strict_gate.py").write_text(f"raise SystemExit({exit_code})\n")
            env = dict(os.environ, STRICT_MODE="prototype")
            return subprocess.run(["bash", str(root / "strict-green-gate.sh"), *arguments],
                                  cwd=root, env=env, capture_output=True, text=True)

    def test_prototype_only_relaxes_affected(self):
        self.assertEqual(self.invoke(["--mode", "affected"], exit_code=1).returncode, 0)
        self.assertEqual(self.invoke(["--mode", "affected"], exit_code=2).returncode, 2)
        for mode in ("completion", "full", "plan"):
            with self.subTest(mode=mode):
                self.assertEqual(self.invoke(["--mode", mode]).returncode, 9)

    def test_equals_and_late_mode_cannot_relax_completion(self):
        for args in (["--mode=completion"], ["--jobs", "1", "--mode", "completion"]):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(args).returncode, 9)

    def test_duplicate_mode_cannot_downgrade_completion(self):
        self.assertNotEqual(self.invoke(["--mode", "completion", "--mode", "affected"]).returncode, 0)
        self.assertEqual(self.invoke(["--mode", "affected", "--mode=full"]).returncode, 2)

    def test_missing_mode_value_fails(self):
        self.assertEqual(self.invoke(["--mode"]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
