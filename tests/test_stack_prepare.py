import importlib.util
import copy
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
import json
import hashlib
import signal
import sys
import time
from unittest import mock


PATH = Path(__file__).parents[1] / "tools" / "stack_prepare.py"
SPEC = importlib.util.spec_from_file_location("stack_prepare", PATH)
prepare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(prepare)


class PrepareContracts(unittest.TestCase):
    def receipt_fixture(self, base):
        root=base/'source'; private=base/'private'; root.mkdir(); private.mkdir(mode=0o700)
        (root/'input').write_text('one'); (root/'output').write_text('existing output')
        manifest={'argv':['false'],'cwd':'.','inputs':['input'],'outputs':['output'],
                  'toolchain':[['python3','--version']],'env':{}}
        path=root/'recipe.json'; path.write_text(json.dumps(manifest))
        forged={'version':1,'identity':prepare._identity(root,manifest),'outputs':prepare._files(root,['output']),
                'success':True,'source_changed':False,'outcome':{'exit_code':0,'output_digest':None},'elapsed_ms':0}
        return root,private,path,manifest,forged

    def check_cli(self, root, private, manifest_path, receipt):
        return subprocess.run(['python3',str(PATH),'--root',str(root),'--manifest',str(manifest_path),
                               '--receipt-root',str(private),'--check-receipt',str(receipt)],
                              capture_output=True,text=True,timeout=3)

    def detached_writer(self):
        writer = ("import os,time\nfrom pathlib import Path\ndeadline=time.monotonic()+2\n"
                  "while time.monotonic()<deadline:\n"
                  " try:\n  os.write(1,b'x'*4096)\n except BrokenPipeError:\n"
                  "  Path('writer-closed').write_text('closed'); break\n"
                  " time.sleep(.005)\n")
        parent = ("import subprocess,sys,time\nfrom pathlib import Path\n"
                  "child=subprocess.Popen([sys.executable,'-c'," + repr(writer) + "],start_new_session=True)\n"
                  "Path('detached.pid').write_text(str(child.pid))\n"
                  "Path('output').write_text('partial output')\ntime.sleep(3)\n")
        return [sys.executable, '-c', parent]

    def cleanup_writer(self, root):
        path = root / 'detached.pid'
        if path.exists():
            try:
                os.kill(int(path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_runner_hashes_complete_merged_multimegabyte_binary_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = b'A' * 2_097_152 + b'\x00\xff', b'B' * 1_048_576 + b'\xfe'
            script = ("import os\nfor fd,data in ((1,b'A'*2097152+b'\\x00\\xff'),(2,b'B'*1048576+b'\\xfe')):\n"
                      " remaining=memoryview(data)\n while remaining:\n  count=os.write(fd,remaining); remaining=remaining[count:]\n")
            result = prepare._run([sys.executable, '-c', script], root, os.environ.copy(), 3)
            self.assertEqual(result, {'exit_code': 0, 'output_digest': hashlib.sha256(first + second).hexdigest()})

    @unittest.skipUnless(os.name == 'posix', 'fixture requires detached POSIX sessions')
    def test_timeout_closes_detached_writer_pipe_and_failure_receipt_is_not_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); root, private, _, manifest, _ = self.receipt_fixture(base)
            manifest.update(argv=self.detached_writer(), timeout_seconds=.3)
            try:
                start = time.monotonic()
                receipt = prepare.run_prepare(root, manifest, receipt_root=private)
                elapsed = time.monotonic() - start
                self.assertEqual(receipt['outcome']['exit_code'], 124)
                self.assertLess(elapsed, 1.3)
                self.assertFalse(receipt['success'])
                self.assertFalse(prepare.is_fresh(root, manifest, receipt))
                self.assertTrue(Path(receipt['receipt_path']).is_file())
                limit = time.monotonic() + .6
                while not (root / 'writer-closed').exists() and time.monotonic() < limit:
                    time.sleep(.01)
                self.assertTrue((root / 'writer-closed').exists(), 'escaped writer kept its output destination writable after timeout')
            finally:
                self.cleanup_writer(root)

    def test_deadline_includes_process_wait_after_output_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            result = prepare._run([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(3)'],
                                  Path(tmp), os.environ.copy(), .1)
            self.assertEqual(result['exit_code'], 124)
            self.assertLess(time.monotonic() - start, 1)

    def test_failed_probe_keeps_failed_receipt_and_never_runs_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, private, _, manifest, _ = self.receipt_fixture(Path(tmp).resolve())
            manifest['toolchain'] = [[sys.executable, '-c', 'import os; os.write(2,b"bad probe\\xff"); raise SystemExit(7)']]
            manifest['argv'] = [sys.executable, '-c', "from pathlib import Path; Path('generator-ran').touch()"]
            receipt = prepare.run_prepare(root, manifest, receipt_root=private)
            self.assertFalse(receipt['success'])
            self.assertFalse(prepare.is_fresh(root, manifest, receipt))
            self.assertFalse((root / 'generator-ran').exists())
            self.assertTrue(Path(receipt['receipt_path']).is_file())

    def test_native_nonposix_execution_rejects_before_launch_or_receipt_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); private = root / 'private'
            with mock.patch.object(prepare.os, 'name', 'nt'), mock.patch.object(prepare.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(prepare.PrepareError, 'POSIX.*WSL'):
                    prepare._run(['not-run'], root, {}, 1)
                with self.assertRaisesRegex(prepare.PrepareError, 'POSIX.*WSL'):
                    prepare.run_prepare(root, {}, receipt_root=private)
                launch.assert_not_called()
            self.assertFalse(private.exists())

    def test_cli_rejects_fabricated_checkout_receipt_before_identity_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,private,manifest_path,manifest,forged=self.receipt_fixture(Path(tmp).resolve())
            subprocess.run(['git','init','-q',str(root)],check=True)
            candidate=root/'forged.json'; candidate.write_text(json.dumps(forged)); candidate.chmod(0o600)
            self.assertTrue(prepare.is_fresh(root,manifest,forged))  # Data alone cannot prove where it came from.
            result=self.check_cli(root,private,manifest_path,candidate)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertNotIn('true',result.stdout)
            self.assertEqual(list(private.iterdir()),[])

    def test_receipt_read_enforces_scope_permissions_symlinks_and_regular_files(self):
        for kind in ('outside','root-mode','file-mode','root-alias','file-alias','fifo','directory','missing-root','oversize'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp).resolve();root,private,manifest_path,_,forged=self.receipt_fixture(base)
                candidate=private/'receipt.json';candidate.write_text(json.dumps(forged));candidate.chmod(0o600)
                supplied=private
                if kind=='outside': candidate=base/'other.json';candidate.write_text(json.dumps(forged));candidate.chmod(0o600)
                elif kind=='root-mode': private.chmod(0o755)
                elif kind=='file-mode': candidate.chmod(0o644)
                elif kind=='root-alias': supplied=base/'alias';supplied.symlink_to(private)
                elif kind=='file-alias': original=private/'original.json';candidate.rename(original);candidate.symlink_to(original)
                elif kind=='fifo': candidate.unlink();os.mkfifo(candidate,0o600)
                elif kind=='directory': candidate.unlink();candidate.mkdir(mode=0o700)
                elif kind=='missing-root': supplied=base/'missing'
                elif kind=='oversize': candidate.write_bytes(b' '*1_048_577)
                result=self.check_cli(root,supplied,manifest_path,candidate)
                self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                self.assertNotIn('true',result.stdout)
                if kind=='missing-root': self.assertFalse(supplied.exists())

    def test_real_receipt_cli_is_fresh_then_stale_without_running_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();root,private,manifest_path,manifest,_=self.receipt_fixture(base)
            manifest['argv']=['python3','-c',"from pathlib import Path; p=Path('runs'); p.write_text(p.read_text()+'x' if p.exists() else 'x'); Path('output').write_text('generated')"]
            manifest_path.write_text(json.dumps(manifest))
            receipt=prepare.run_prepare(root,manifest,receipt_root=private)
            self.assertEqual(self.check_cli(root,private,manifest_path,receipt['receipt_path']).returncode,0)
            (root/'input').write_text('two')
            self.assertEqual(self.check_cli(root,private,manifest_path,receipt['receipt_path']).returncode,1)
            self.assertEqual((root/'runs').read_text(),'x')

    def test_freshness_probe_cannot_leave_receipt_storage_unprotected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,private,manifest_path,manifest,forged=self.receipt_fixture(Path(tmp).resolve())
            manifest['toolchain']=[['python3','-c','from pathlib import Path; Path('+repr(str(private))+').chmod(0o755)']]
            forged['identity']=prepare._identity(root,manifest);private.chmod(0o700)
            manifest_path.write_text(json.dumps(manifest))
            candidate=private/'receipt.json';candidate.write_text(json.dumps(forged));candidate.chmod(0o600)
            result=self.check_cli(root,private,manifest_path,candidate)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertNotIn('true',result.stdout)

    def test_dotdot_cannot_put_receipts_inside_nongit_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,private,_,manifest,_=self.receipt_fixture(Path(tmp).resolve())
            requested=private/'..'/'source'/'receipts'
            with self.assertRaises(prepare.PrepareError):
                prepare.run_prepare(root,manifest,receipt_root=requested)
            self.assertFalse((root/'receipts').exists())

    def test_receipts_reject_canonical_store_case_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); root = base / 'source'; root.mkdir()
            for name in ('MeMoRiEs', 'SeSsIoNs'):
                target = base / '.CoDeX' / name
                with self.subTest(name=name), self.assertRaisesRegex(prepare.PrepareError, 'canonical records'):
                    prepare._receipt_directory(root, target)
                self.assertFalse(target.exists())

    def test_receipts_reject_symlink_exposed_by_normalizing_missing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); root = base / 'source'; root.mkdir()
            private = base / 'private'; private.mkdir(mode=0o700)
            (base / 'alias').symlink_to(private, target_is_directory=True)
            target = base / 'missing' / '..' / 'alias' / 'receipts'
            with self.assertRaisesRegex(prepare.PrepareError, 'symlink'):
                prepare._receipt_directory(root, target)
            self.assertFalse((private / 'receipts').exists())

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

    def test_malformed_destination_repository_rejects_before_preparation_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(); root, _, _, manifest, _ = self.receipt_fixture(base)
            other = base / 'other-repo'
            subprocess.run(['git', 'init', '-q', str(other)], check=True)
            nested = other / 'nested'; nested.mkdir()
            config = other / '.git/config'; config.write_text(config.read_text() + '\n[malformed\n')
            manifest['argv'] = ['python3', '-c', "from pathlib import Path; Path('command-ran').write_text('ran'); Path('output').write_text('new output')"]
            before = (root / 'output').read_bytes()
            with self.assertRaises(prepare.PrepareError):
                prepare.run_prepare(root, manifest, receipt_root=nested / 'receipts')
            self.assertFalse((root / 'command-ran').exists())
            self.assertFalse((nested / 'receipts').exists())
            self.assertEqual((root / 'output').read_bytes(), before)

    def test_duplicate_recipe_keys_reject_before_probe_or_generator(self):
        for field in ('argv', 'env'):
            for reverse in (False, True):
                with self.subTest(field=field, reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                    root, private, manifest_path, manifest, _ = self.receipt_fixture(Path(tmp).resolve())
                    script = "from pathlib import Path; Path('command-ran').write_text('ran'); Path('output').write_text('generated')"
                    manifest['argv'] = ['python3', '-c', script]
                    manifest['toolchain'] = [['python3', '-c', "from pathlib import Path; Path('probe-ran').write_text('ran')"]]
                    manifest['env'] = {'MODE': 'one'}
                    content = json.dumps(manifest)
                    if field == 'argv':
                        values = [manifest['argv'], ['python3', '-c', script + "; print('other command')"]]
                        if reverse: values.reverse()
                        replacement = ', '.join('"argv": ' + json.dumps(value) for value in values)
                        content = content.replace('"argv": ' + json.dumps(manifest['argv']), replacement)
                    else:
                        values = ['one', 'two'] if not reverse else ['two', 'one']
                        replacement = ', '.join('"MODE": ' + json.dumps(value) for value in values)
                        content = content.replace('"MODE": "one"', replacement)
                    manifest_path.write_text(content)
                    result = subprocess.run(['python3', str(PATH), '--root', str(root), '--manifest', str(manifest_path),
                                             '--receipt-root', str(private)], capture_output=True, text=True, timeout=3)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertFalse((root / 'command-ran').exists())
                    self.assertFalse((root / 'probe-ran').exists())
                    self.assertEqual((root / 'output').read_text(), 'existing output')
                    self.assertEqual(list(private.iterdir()), [])

    def test_duplicate_receipt_keys_cannot_be_fresh_in_either_order(self):
        for field in ('success', 'exit_code', 'recipe_digest'):
            for reverse in (False, True):
                with self.subTest(field=field, reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                    root, private, manifest_path, _, receipt = self.receipt_fixture(Path(tmp).resolve())
                    valid = receipt['success'] if field == 'success' else receipt['outcome']['exit_code'] if field == 'exit_code' else receipt['identity']['recipe_digest']
                    invalid = False if field == 'success' else 7 if field == 'exit_code' else 'stale'
                    values = [invalid, valid] if not reverse else [valid, invalid]
                    replacement = ', '.join(json.dumps(field) + ': ' + json.dumps(value) for value in values)
                    content = json.dumps(receipt).replace(json.dumps(field) + ': ' + json.dumps(valid), replacement)
                    path = private / 'receipt.json'; path.write_text(content); path.chmod(0o600)
                    result = self.check_cli(root, private, manifest_path, path)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertNotIn('true', result.stdout)
                    self.assertEqual(path.read_text(), content)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual((root / 'output').read_text(), 'existing output')
