from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "test" / "public-safety-test.sh"


class PublicSafetyTests(unittest.TestCase):
    def test_standalone_openai_project_key_blocks_public_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test").mkdir()
            shutil.copy2(SCRIPT, root / "test" / "public-safety-test.sh")
            credential = "sk-" + "proj-" + "AbCdEf0123456789_-" * 3
            (root / "config.txt").write_text("credential " + credential + "\n")
            subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
            subprocess.run(
                ["git", "add", "config.txt", "test/public-safety-test.sh"],
                cwd=root,
                check=True,
            )

            completed = subprocess.run(
                ["bash", "test/public-safety-test.sh"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("config.txt", completed.stderr)
