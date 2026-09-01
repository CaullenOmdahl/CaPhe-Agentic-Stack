from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "test" / "public-safety-test.sh"


class PublicSafetyTests(unittest.TestCase):
    def _repo_with_scanner(self, root: Path) -> None:
        (root / "test").mkdir()
        shutil.copy2(SCRIPT, root / "test" / "public-safety-test.sh")
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)

    def test_standalone_openai_project_key_blocks_public_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_scanner(root)
            credential = "sk-" + "proj-" + "AbCdEf0123456789_-" * 3
            (root / "config.txt").write_text("credential " + credential + "\n")
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
            self.assertNotIn(credential, completed.stdout + completed.stderr)

    def test_secret_in_staged_blob_is_scanned_after_worktree_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_scanner(root)
            credential = "sk-" + "proj-" + "AbCdEf0123456789_-" * 3
            config = root / "config.txt"
            config.write_text("credential " + credential + "\n" + ("x" * 5_000_000))
            subprocess.run(
                ["git", "add", "config.txt", "test/public-safety-test.sh"],
                cwd=root,
                check=True,
            )
            config.write_text("sanitized worktree\n")

            completed = subprocess.run(
                ["bash", "test/public-safety-test.sh"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("config.txt", completed.stderr)
            self.assertNotIn(credential, completed.stdout + completed.stderr)
