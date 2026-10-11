"""Distribution contracts: inspect real installed policy and initialized projects."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load('simplification_install', ROOT / 'tools/stack_install.py')
initializer = load('simplification_init', ROOT / 'strict-mode/bin/strict_init.py')


class InstalledWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='caphe-workflow-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.task_home = self.root / 'home'
        self.task_home.mkdir()
        env = {'HOME': str(self.task_home)}
        for kind in ('CONFIG', 'DATA', 'STATE', 'CACHE'):
            directory = self.root / ('xdg-' + kind.lower())
            directory.mkdir()
            env['XDG_' + kind + '_HOME'] = str(directory)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)

    def project(self):
        repo = self.root / 'project'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        return repo

    def install(self):
        runtime = self.task_home / 'runtime'
        plan = installer.plan_runtime_install(ROOT, runtime)
        result = installer.apply_runtime_plan(plan, inventory_root=self.root / 'inventory')
        self.assertTrue(result['verified'])
        self.assertTrue(installer.verify_runtime_plan(plan))
        return runtime

    def test_installed_policy_covers_routine_meaningful_optional_and_high_risk_paths(self):
        runtime = self.install()
        canon = (runtime / 'docs/canon.md').read_text()
        self.assertEqual((runtime / 'docs/workflow-examples.md').read_bytes(),
                         (ROOT / 'docs/workflow-examples.md').read_bytes())
        cases = {
            'routine': ('routine small reversible changes', 'do not need a planning document', 'Run relevant checks'),
            'behavior': ('Add/update regression coverage when it protects', 'inspect the actual result',
                         'separately performed diff review when useful', 'reviewer may use the same model family'),
            'optional': ('Optional QA must not block closure', 'Evidence-only updates do not restart implementation'),
            'high-risk': ('scoped human', 'private-memory boundaries',
                          'exact or standing human authorization', 'release or deployment'),
        }
        for scenario, requirements in cases.items():
            with self.subTest(scenario=scenario):
                for requirement in requirements:
                    self.assertIn(requirement, canon)
        for relative in ('strict-mode/methodology.md', 'skills/strict-mode/SKILL.md',
                         'strict-mode/templates/instruction-section.md', 'strict-mode/templates/dod-checklist.md'):
            with self.subTest(adapter=relative):
                text = (runtime / relative).read_text()
                self.assertIn('canon', text)
                for obsolete in ('completion requires --mode completion', 'completion requires\n',
                                 'write immutable v2 `.agent/evidence/` snapshots'):
                    self.assertNotIn(obsolete, text)

    def test_fresh_activation_has_no_stop_gate_and_preserves_custom_hook(self):
        runtime = self.install()
        repo = self.project()
        hooks = repo / '.git/hooks'
        original = hooks / 'pre-commit'
        original.write_text('#!/bin/sh\nexit 0\n')
        original.chmod(0o755)
        (repo / 'AGENTS.md').write_text('Owner-specific project instructions\n')
        result = installer.initialize_project(runtime, repo, apply=True)
        self.assertEqual(result['state'], 'initialized')
        self.assertFalse((repo / '.claude/settings.json').exists())
        self.assertIn('Owner-specific project instructions', (repo / 'AGENTS.md').read_text())
        self.assertEqual(original.read_text(), '#!/bin/sh\nexit 0\n')
        self.assertIn('canon', (repo / 'AGENTS.md').read_text())
        self.assertNotIn('completion requires', (repo / 'AGENTS.md').read_text())

    def test_refresh_retires_only_exact_generated_stop_and_is_idempotent(self):
        repo = self.project()
        canon = ROOT / 'strict-mode'
        settings = repo / '.claude/settings.json'
        settings.parent.mkdir()
        legacy = {'hooks': [{'type': 'command', 'command':
            shlex.quote(str(canon / 'bin/strict-green-gate.sh')) + ' --mode completion || true'}]}
        custom = {'hooks': [{'type': 'command', 'command': 'echo owner-check'}]}
        data = {'permissions': {'deny': ['Write(secrets/**)']},
                'hooks': {'Stop': [legacy, custom], 'PreToolUse': [custom]}}
        settings.write_text(json.dumps(data))
        settings.chmod(0o640)
        initializer.initialize(canon, repo)
        expected = {'permissions': data['permissions'], 'hooks': {'Stop': [custom], 'PreToolUse': [custom]}}
        self.assertEqual(json.loads(settings.read_text()), expected)
        self.assertEqual(settings.stat().st_mode & 0o777, 0o640)
        before = settings.read_bytes()
        initializer.initialize(canon, repo)
        self.assertEqual(settings.read_bytes(), before)

    def test_known_stock_policy_refreshes_but_custom_policy_stays_intact(self):
        repo = self.project()
        agent = repo / '.agent'
        agent.mkdir()
        for relative, digest in initializer.PRIOR_STOCK_POLICY.items():
            fixture = 'owners-prior-stock.md' if Path(relative).name == 'OWNERS.md' else 'checklist-prior-stock.md'
            content = (ROOT / 'tests/fixtures' / fixture).read_bytes()
            self.assertEqual(initializer._sha(content), digest)
            (repo / relative).write_bytes(content)
        initializer.initialize(ROOT / 'strict-mode', repo)
        for relative in initializer.PRIOR_STOCK_POLICY:
            self.assertEqual((repo / relative).read_bytes(),
                (ROOT / 'strict-mode/templates' / Path(relative).name).read_bytes())
            (repo / relative).write_text('Owner custom constraints\n')
        initializer.initialize(ROOT / 'strict-mode', repo)
        for relative in initializer.PRIOR_STOCK_POLICY:
            self.assertEqual((repo / relative).read_text(), 'Owner custom constraints\n')

    def test_refresh_rolls_back_hook_retirement_on_failed_activation(self):
        repo = self.project()
        canon = ROOT / 'strict-mode'
        settings = repo / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command':
            shlex.quote(str(canon / 'bin/strict-green-gate.sh')) + ' --mode completion || true'}]}]}}))
        before = settings.read_bytes()
        with self.assertRaises(initializer.InitError):
            initializer.initialize(canon, repo, fail_probe=True)
        self.assertEqual(settings.read_bytes(), before)

    def test_custom_malformed_and_foreign_path_hooks_are_not_reinterpreted(self):
        for content in ('not json', '[]', '{"hooks": {}, "hooks": {}}', '{"hooks": []}', '{"hooks":{"Stop":"custom"}}',
                        '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"other-runtime --mode completion || true"}]}]}}'):
            with self.subTest(content=content):
                self.assertIsNone(initializer.retire_completion_stop(content, ROOT / 'strict-mode'))


if __name__ == '__main__':
    unittest.main()
