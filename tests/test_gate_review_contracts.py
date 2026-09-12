"""Executable regressions for findings carried in PR review bodies."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SPEC = importlib.util.spec_from_file_location('gate_body_review', Path(__file__).parents[1] / 'strict-mode/bin/strict_gate.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def component(name):
    return {'name': name, 'paths': [name+'/**'], 'depends_on': [],
            'dependency_verification': {'kind': 'custom', 'command': [sys.executable, '-c', 'pass']},
            'commands': [{'name': 'test', 'run': [sys.executable, '-c', 'pass']}]}


class ReviewBodyContracts(unittest.TestCase):
    def test_command_cwd_cannot_escape_before_command_or_cache_probe(self):
        for kind in ('absolute', 'parent', 'symlink', 'cached-symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                base=Path(temporary).resolve(); root=base/'root'; root.mkdir(); outside=base/'outside'; outside.mkdir()
                (root/'input').write_text('cache input')
                (root/'escape').symlink_to(outside, target_is_directory=True)
                cwd=str(outside) if kind=='absolute' else '../outside' if kind=='parent' else 'escape'
                command=gate.CommandSpec('fixture','escape',(sys.executable,'-c',"from pathlib import Path; Path('command-ran').write_text('ran')"),
                                         cwd=cwd, cache_allowed=kind=='cached-symlink', cache_inputs=('input',),
                                         toolchain=((sys.executable,'-c',"from pathlib import Path; Path('probe-ran').write_text('ran')"),))
                if command.cache_allowed:
                    with self.assertRaises(gate.ManifestError): gate.cache_key(root,command,'manifest')
                with self.assertRaises(gate.ManifestError): gate._run_one(root,command,'manifest',root/'cache')
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((root/'cache').exists())

    def test_custom_verifier_timeout_falls_back_to_full_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); slow=component('slow'); other=component('other')
            slow['dependency_verification'].update(command=[sys.executable,'-c','import time; time.sleep(1)'],timeout_seconds=0.05)
            data={'version':1,'components':[slow,other]}
            gate.validate_manifest(data)
            started=time.monotonic(); verified=gate.verify_dependency_completeness(root,data)
            self.assertNotIn('slow',verified)
            self.assertIn('other',verified)
            self.assertLess(time.monotonic()-started,0.8)
            plan=gate.build_plan(data,['slow/file'],mode='affected',verified_dependencies=verified)
            self.assertEqual({command.component for command in plan},{'slow','other'})
            self.assertFalse((root/'.agent').exists())

    def test_generated_node_command_names_preserve_distinct_package_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for cwd in ('apps/foo-bar','apps/foo/bar'):
                directory=root/cwd; directory.mkdir(parents=True)
                (directory/'package.json').write_text(json.dumps({'scripts':{'test':'test command','lint':'lint command'}}))
            manifest=gate.discover_default_manifest(root)
            gate.validate_manifest(manifest)
            commands=[command for command in manifest['components'][0]['commands'] if command['name'].startswith('npm-')]
            self.assertEqual(len(commands),4)
            self.assertEqual(len({command['name'] for command in commands}),4)
            self.assertEqual({command['cwd'] for command in commands},{'apps/foo-bar','apps/foo/bar'})
            self.assertEqual(manifest,gate.discover_default_manifest(root))

    def test_ancestor_unittest_does_not_import_or_run_separately_scheduled_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary); root=base/'root'; root.mkdir(); child=root/'package'; child.mkdir()
            for directory in (root,child): (directory/'pyproject.toml').write_text("[project]\nname='fixture'\nversion='0.1.0'\n")
            ordinary=root/'ordinary'; ordinary.mkdir()
            (ordinary/'__init__.py').write_text("import os, unittest\nclass Loaded(unittest.TestCase):\n    def test_loaded(self):\n        with open(os.environ['CAPHE_RUN_LOG'],'a') as log: log.write('ordinary\\n')\ndef load_tests(loader, tests, pattern):\n    return loader.loadTestsFromTestCase(Loaded)\n")
            (child/'__init__.py').write_text("import os\nfrom pathlib import Path\nPath(os.environ['CAPHE_IMPORT_LOG']).write_text('ancestor imported child')\n")
            for directory,label in ((root,'parent'),(child,'child')):
                (directory/('test_'+label+'.py')).write_text("import os, unittest\nclass Fixture(unittest.TestCase):\n    def test_runs_once(self):\n        with open(os.environ['CAPHE_RUN_LOG'],'a') as log: log.write('"+label+"\\n')\n")
            data=gate.discover_default_manifest(root); gate.validate_manifest(data)
            commands=[command for command in data['components'][0]['commands'] if command['name'].startswith('python-')]
            self.assertEqual(len(commands),2)
            environment={**os.environ,'CAPHE_RUN_LOG':str(base/'runs'),'CAPHE_IMPORT_LOG':str(base/'imports')}
            for command in commands:
                result=subprocess.run(command['run'],cwd=root/command.get('cwd','.'),env=environment,capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(sorted((base/'runs').read_text().splitlines()),['child','ordinary','parent'])
            self.assertFalse((base/'imports').exists())

    def test_cwd_manifest_validation_and_internal_execution(self):
        for cwd in ('/outside', '../outside', 'safe/../outside', r'C:\outside', '', None, 4):
            with self.subTest(cwd=cwd):
                data={'version':1,'components':[component('fixture')]}
                data['components'][0]['commands'][0]['cwd']=cwd
                with self.assertRaises(gate.ManifestError): gate.validate_manifest(data)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/'inside').mkdir()
            command=gate.CommandSpec('fixture','inside',(sys.executable,'-c',"from pathlib import Path; Path('ran').write_text('inside')"),cwd='inside')
            self.assertEqual(gate._run_one(root,command,'manifest',root/'cache')[1],0)
            self.assertEqual((root/'inside/ran').read_text(),'inside')

    def test_plan_preflights_every_cwd_before_first_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            first=gate.CommandSpec('fixture','first',(sys.executable,'-c',"from pathlib import Path; Path('ran').write_text('bad')"))
            second=gate.CommandSpec('fixture','second',(sys.executable,'-c','pass'),cwd='../outside')
            with self.assertRaises(gate.ManifestError):
                gate.execute_plan(root,[first,second],'manifest',1)
            self.assertFalse((root/'ran').exists())

    def test_custom_verifier_timeout_configuration_is_finite(self):
        for timeout in (None, True, 0, -1, float('inf'), float('nan'), '10'):
            with self.subTest(timeout=timeout):
                data={'version':1,'components':[component('fixture')]}
                data['components'][0]['dependency_verification']['timeout_seconds']=timeout
                with self.assertRaises(gate.ManifestError): gate.validate_manifest(data)
        from unittest import mock
        with tempfile.TemporaryDirectory() as temporary:
            data={'version':1,'components':[component('fixture')]}
            with mock.patch.object(gate,'_run_one',return_value=(None,0,'',False)) as run:
                self.assertEqual(gate.verify_dependency_completeness(Path(temporary),data),{'fixture'})
            self.assertEqual(run.call_args.args[1].timeout_seconds,10)

    @unittest.skipUnless(os.name=='posix','process group lifecycle is POSIX-specific')
    def test_verifier_deadline_terminates_child_holding_output_pipes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            child="import time; from pathlib import Path; Path('child-started').write_text('yes'); time.sleep(0.5); Path('survived').write_text('bad')"
            parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"+repr(child)+"]); time.sleep(5)"
            verifier=component('fixture')
            verifier['dependency_verification'].update(command=[sys.executable,'-c',parent],timeout_seconds=0.2)
            started=time.monotonic()
            self.assertEqual(gate.verify_dependency_completeness(root,{'version':1,'components':[verifier]}),set())
            self.assertLess(time.monotonic()-started,1)
            self.assertTrue((root/'child-started').exists())
            time.sleep(0.5)
            self.assertFalse((root/'survived').exists())
