import importlib.util
import copy
import os
from pathlib import Path
import tempfile
import unittest
import subprocess


PATH = Path(__file__).parents[1] / "tools" / "stack_prepare.py"
SPEC = importlib.util.spec_from_file_location("stack_prepare", PATH)
prepare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(prepare)


class PrepareContracts(unittest.TestCase):
    def test_manifest_rejects_shell_strings_and_env_copying(self):
        with self.assertRaises(prepare.PrepareError):
            prepare.validate_manifest({"argv": "echo unsafe", "cwd": ".", "inputs": [], "outputs": [], "toolchain": [], "env": {}})
        with self.assertRaises(prepare.PrepareError):
            prepare.validate_manifest({"argv": ["echo", "ok"], "cwd": ".", "inputs": [], "outputs": [], "toolchain": [], "env": {"HOME": "$HOME"}})

    def test_prepare_receipt_is_private_source_bound_and_freshness_tracks_input_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp); (root / "input.txt").write_text("one")
            manifest = {"argv": ["python3", "-c", "open('output.txt','w').write('ok')"], "cwd": ".", "inputs": ["input.txt"], "outputs": ["output.txt"], "toolchain": [["python3", "--version"]], "env": {}}
            receipt = prepare.run_prepare(root, manifest, receipt_root=Path(private).resolve())
            self.assertTrue(receipt["success"])
            self.assertTrue(prepare.is_fresh(root, manifest, receipt))
            self.assertEqual((Path(private).stat().st_mode & 0o077), 0)
            changed_recipe = {**manifest, "argv": ["python3", "-c", "pass"]}
            self.assertFalse(prepare.is_fresh(root, changed_recipe, receipt))
            changed_outputs = {**manifest, "outputs": ["other.txt"]}
            self.assertFalse(prepare.is_fresh(root, changed_outputs, receipt))
            forged = copy.deepcopy(receipt)
            forged["outputs"] = {}
            self.assertFalse(prepare.is_fresh(root, manifest, forged))
            (root / "input.txt").write_text("two")
            self.assertFalse(prepare.is_fresh(root, manifest, receipt))

    def test_missing_tool_or_output_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp)
            manifest = {"argv": ["definitely-not-a-tool"], "cwd": ".", "inputs": ["absent"], "outputs": ["missing"], "toolchain": [["definitely-not-a-tool", "--version"]], "env": {}}
            receipt = prepare.run_prepare(root, manifest, receipt_root=Path(private).resolve())
            self.assertFalse(receipt["success"])
            self.assertFalse(prepare.is_fresh(root, manifest, receipt))

    def test_private_receipt_cannot_be_in_any_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "input").write_text("one")
            manifest = {"argv": ["python3", "-c", "pass"], "cwd": ".", "inputs": ["input"], "outputs": ["output"], "toolchain": [["python3", "--version"]], "env": {}}
            with self.assertRaises(prepare.PrepareError):
                prepare.run_prepare(root, manifest, receipt_root=root / "receipts")
            self.assertFalse((root / "receipts").exists())

    def test_source_mutation_and_output_symlinks_cannot_be_fresh(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp)
            (root / "input").write_text("one")
            recipe = "from pathlib import Path; Path('input').write_text('two'); Path('output').write_text('ok')"
            manifest = {"argv": ["python3", "-c", recipe], "cwd": ".", "inputs": ["input"], "outputs": ["output"], "toolchain": [["python3", "--version"]], "env": {}}
            receipt = prepare.run_prepare(root, manifest, receipt_root=Path(private).resolve())
            self.assertFalse(receipt["success"])
            (root / "output").unlink()
            (root / "output").symlink_to(Path(private) / "canary")
            with self.assertRaises(prepare.PrepareError):
                prepare.run_prepare(root, manifest, receipt_root=Path(private).resolve())

    def test_failed_recipe_cli_is_nonzero_and_keeps_output_private(self):
        import json
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp)
            (root / "input").write_text("one")
            manifest = {"argv": ["python3", "-c", "print('SECRET_CANARY'); raise SystemExit(9)"], "cwd": ".", "inputs": ["input"], "outputs": ["output"], "toolchain": [["python3", "--version"]], "env": {}}
            path = root / "recipe.json"
            path.write_text(json.dumps(manifest))
            result = subprocess.run(["python3", str(PATH), "--root", str(root), "--manifest", str(path), "--receipt-root", str(Path(private).resolve())], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("SECRET_CANARY", result.stdout + result.stderr)

    def test_probe_mutation_invalidates_identity_and_malformed_receipt_is_not_fresh(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp).resolve()
            (root / "input").write_text("one")
            manifest = {"argv": ["python3", "-c", "open('output','w').write('ok')"], "cwd": ".", "inputs": ["input"], "outputs": ["output"], "toolchain": [["python3", "--version"]], "env": {}}
            receipt = prepare.run_prepare(root, manifest, receipt_root=Path(private).resolve())
            self.assertFalse(prepare.is_fresh(root, manifest, {**receipt, "outcome": None}))
            manifest['toolchain'] = [["python3", "-c", "open('input','w').write('changed'); print('v1')"]]
            with self.assertRaises(prepare.PrepareError):
                prepare.run_prepare(root, manifest, receipt_root=Path(private).resolve())

    def test_fifo_and_changed_receipt_directory_fail_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as private:
            root = Path(tmp).resolve()
            os.mkfifo(root / "input")
            manifest = {"argv": ["python3", "-c", "pass"], "cwd": ".", "inputs": ["input"], "outputs": ["output"], "toolchain": [["python3", "--version"]], "env": {}}
            import json
            recipe_path = root / 'recipe.json'
            recipe_path.write_text(json.dumps(manifest))
            blocked = subprocess.run(['python3', str(PATH), '--root', str(root), '--manifest', str(recipe_path),
                                      '--receipt-root', str(Path(private).resolve())],
                                     capture_output=True, text=True, timeout=2)
            self.assertEqual(blocked.returncode, 2)
            (root / "input").unlink(); (root / "input").write_text('one')
            receipts = Path(private).resolve() / 'receipts'
            code = "from pathlib import Path; p=Path(" + repr(str(receipts)) + "); p.rename(p.with_name('moved')); p.symlink_to(Path.cwd(), target_is_directory=True); Path('output').write_text('ok')"
            manifest['argv'] = ['python3', '-c', code]
            with self.assertRaises(prepare.PrepareError):
                prepare.run_prepare(root, manifest, receipt_root=receipts)
            self.assertEqual(list(root.glob('prepare-*.json')), [])

    def test_cli_errors_do_not_echo_private_input_paths(self):
        result = subprocess.run(['python3', str(PATH), '--manifest', 'missing-token=ERROR_CANARY', '--receipt-root', '.'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('ERROR_CANARY', result.stdout + result.stderr)
