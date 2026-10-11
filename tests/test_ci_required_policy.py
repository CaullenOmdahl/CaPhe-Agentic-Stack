"""Exercise ordinary CI validation; policy source is a product, not a certification framework."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ('strict-mode/test/shell-syntax-test.sh', 'strict-mode/test/strict-confer-isolation-test.sh',
          'strict-mode/test/strict-init-refresh-test.sh', 'test/public-safety-test.sh')


def workflow_script():
    lines = (ROOT / '.github/workflows/quality.yml').read_text().splitlines()
    start = lines.index('        run: |') + 1
    return '\n'.join(line[10:] for line in lines[start:]) + '\n'


class RepositoryValidationTests(unittest.TestCase):
    def run_checks(self, *, python_failure=False, shell_failure=False, shadow=False,
                   python_environment=False, mutate=False):
        with tempfile.TemporaryDirectory(prefix='caphe-ci-test-') as tmp:
            root = Path(tmp).resolve()
            repo = root / 'repo'
            repo.mkdir()
            real_home = root / 'original-home'
            real_home.mkdir()
            runner_temp = root / 'runner-temp'
            runner_temp.mkdir()
            tests = repo / 'tests'
            tests.mkdir()
            (repo / '.gitignore').write_text('__pycache__/\n')
            (repo / 'product.py').write_text('result = 42\n')
            (tests / 'test_product.py').write_text(
                'import os, unittest\nfrom pathlib import Path\nimport product\n'
                'class Product(unittest.TestCase):\n'
                '    def test_actual_product(self):\n'
                '        self.assertEqual(product.result, 42)\n'
                '        self.assertNotEqual(os.environ["HOME"], os.environ["ORIGINAL_HOME"])\n'
                '        self.assertTrue(Path(os.environ["HOME"]).is_dir())\n'
                '        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):\n'
                '            self.assertTrue(Path(os.environ[key]).is_dir())\n'
                '        self.assertNotIn("PYTHONHOME", os.environ)\n'
                '        self.assertNotIn("PYTHONPATH", os.environ)\n'
                '        Path(os.environ["HOME"], "installer-artifact").write_text("disposable")\n'
                + ('        self.fail("actual regression failed")\n' if python_failure else '')
                + ('        Path("product.py").write_text("mutated")\n' if mutate else ''))
            if shadow:
                (repo / 'unittest.py').write_text('raise RuntimeError("SHADOWED RUNNER")\n')
            for index, relative in enumerate(CHECKS):
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#!/usr/bin/env bash\n'
                                'printf "%s\\n" ' + str(index) + ' >> "$CHECK_LOG"\n'
                                + ('exit 3\n' if shell_failure and index == 0 else 'exit 0\n'))
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c',
                            'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
            env.update(HOME=str(real_home), ORIGINAL_HOME=str(real_home),
                       RUNNER_TEMP=str(runner_temp), CHECK_LOG=str(root / 'checks'))
            if python_environment:
                env.update(PYTHONHOME=str(root / 'invalid-python'), PYTHONPATH=str(repo))
            result = subprocess.run(['bash', '-c', workflow_script()], cwd=repo, env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual((root / 'checks').read_text().splitlines(), ['0', '1', '2', '3'])
            self.assertEqual(list(real_home.iterdir()), [])
            self.assertEqual(list(runner_temp.iterdir()), [])
            return result

    def test_product_tests_run_once_and_home_is_disposable(self):
        result = self.run_checks()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ran 1 test', result.stderr)

    def test_python_failure_is_visible_and_does_not_skip_security_checks(self):
        result = self.run_checks(python_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('actual regression failed', result.stderr)

    def test_shell_failure_is_visible_and_later_checks_still_run(self):
        result = self.run_checks(shell_failure=True)
        self.assertNotEqual(result.returncode, 0)

    def test_stdlib_shadow_cannot_skip_python_regressions(self):
        result = self.run_checks(shadow=True, python_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('actual regression failed', result.stderr)
        self.assertNotIn('SHADOWED RUNNER', result.stderr)

    def test_inherited_python_config_is_cleared(self):
        result = self.run_checks(python_environment=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tests_cannot_silently_change_tracked_product(self):
        result = self.run_checks(mutate=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OK', result.stderr)

    def test_workflow_is_manual_only_single_platform_with_read_only_credentials(self):
        text = (ROOT / '.github/workflows/quality.yml').read_text()
        self.assertIn('runs-on: ubuntu-latest', text)
        self.assertIn('workflow_dispatch:', text)
        self.assertNotIn('pull_request:', text)
        self.assertNotIn('push:', text)
        self.assertNotIn('matrix:', text)
        self.assertIn('contents: read', text)
        self.assertIn('persist-credentials: false', text)
        self.assertNotIn('required-policy', text)
        self.assertEqual(text.count('unittest.main('), 1)
