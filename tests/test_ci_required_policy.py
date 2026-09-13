"""Run the actual workflow shell against separate candidate and accepted-policy fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def workflow_scripts():
    lines = (ROOT / ".github/workflows/quality.yml").read_text().splitlines()
    scripts = []
    for index, line in enumerate(lines):
        if line != "        run: |": continue
        result = []
        for following in lines[index + 1:]:
            if following and not following.startswith("          "): break
            result.append(following[10:])
        scripts.append("\n".join(result) + "\n")
    return scripts


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   stderr=subprocess.PIPE).strip()


def commit(root):
    git(root, "init", "-q")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "core.hooksPath", "/dev/null")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


class RequiredPolicyWorkflowTests(unittest.TestCase):
    def run_workflow(self, *, failure=False, mutation=False, wrong_ref=False, replaced_checks=False,
                     product_bad=False, new_candidate_failure=False, run_candidate=False, temp_alias=False,
                     shadow_runner=False, python_environment=False, candidate_required_failure=False,
                     candidate_required_success=False):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            candidate = workspace / "candidate"; candidate.mkdir()
            policy = workspace / "required-policy"; policy.mkdir()
            for root in (candidate, policy):
                (root / "strict-mode/bin").mkdir(parents=True)
                (root / ".agent").mkdir()
                (root / '.gitignore').write_text('__pycache__/\n')
            # Either candidate file would make the former single-step workflow falsely pass.
            (candidate / "strict-mode/bin/strict_gate.py").write_text("print('CANDIDATE NOOP')\n")
            (candidate / "source.txt").write_text("broken\n" if product_bad else "original\n")
            (policy / "source.txt").write_text("original\n")
            for root in (candidate, policy):
                for relative in ('tests', 'test', 'strict-mode/test'):
                    (root / relative).mkdir(parents=True, exist_ok=True)
                    (root / relative / '.keep').write_text('fixture')
            # The fixture runner deliberately has no source guard: the workflow must supply it.
            (policy / "strict-mode/bin/strict_gate.py").write_text(
                "import argparse,json,subprocess,sys\n"
                "p=argparse.ArgumentParser();p.add_argument('--manifest');p.add_argument('--mode');a=p.parse_args()\n"
                "assert a.mode=='completion'\n"
                "commands=json.load(open(a.manifest))['commands']\n"
                "codes=[subprocess.run(command).returncode for command in commands]\n"
                "sys.exit(any(codes))\n")
            commands = [["python3", "-c", f"print('REQUIRED {i}')"] for i in range(4)]
            if temp_alias:
                commands[0][-1] += "; import tempfile; from pathlib import Path; p=Path(tempfile.gettempdir()); assert p == p.resolve()"
            if failure:
                commands[1][-1] += "; raise SystemExit(7)"
            if mutation:
                target = 'tests/.keep' if mutation == 'harness' else 'source.txt'
                commands[1][-1] += "; from pathlib import Path; Path(" + repr(target) + ").write_text('changed')"
            if replaced_checks:
                (policy / 'tests/test_retained.py').write_text(
                    "from pathlib import Path\nimport unittest\n"
                    "class Retained(unittest.TestCase):\n"
                    "    def test_candidate_product(self):\n"
                    "        self.assertEqual((Path(__file__).parents[1]/'source.txt').read_text(),'original\\n')\n")
                (candidate / 'tests/test_retained.py').write_text(
                    "import unittest\nclass Trivial(unittest.TestCase):\n    def test_trivial(self): pass\n")
                commands = [['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-v']]
                for relative in ('strict-mode/test/shell-syntax-test.sh',
                                 'strict-mode/test/strict-confer-isolation-test.sh', 'test/public-safety-test.sh'):
                    (policy / relative).write_text("#!/usr/bin/env bash\nset -eu\ntest \"$(cat source.txt)\" = original\n")
                    (candidate / relative).write_text("#!/usr/bin/env bash\nexit 0\n")
                    commands.append(['bash', relative])
            if shadow_runner:
                (candidate / 'unittest.py').write_text("print('SHADOWED STDLIB RUNNER')\n")
                for relative in ('strict-mode/test/shell-syntax-test.sh',
                                 'strict-mode/test/strict-confer-isolation-test.sh', 'test/public-safety-test.sh'):
                    (policy / relative).write_text("#!/usr/bin/env bash\nexit 0\n")
            if new_candidate_failure:
                (candidate / 'tests/test_added.py').write_text(
                    "import unittest\nclass Added(unittest.TestCase):\n    def test_added(self): self.fail('candidate added test ran')\n")
            candidate_commands = list(commands) if run_candidate else []
            if candidate_required_failure:
                candidate_commands = [["python3", "-c", "print('CANDIDATE REQUIRED'); raise SystemExit(8)"]]
            elif candidate_required_success:
                candidate_commands = [["python3", "-c", "print('CANDIDATE REQUIRED')"]]
            (candidate / ".agent/strict-gate.json").write_text(json.dumps({"commands": candidate_commands}))
            (policy / ".agent/strict-gate.json").write_text(json.dumps({"commands": commands}))
            commit(candidate)
            revision = commit(policy)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            environment.update(GITHUB_WORKSPACE=str(workspace), RUNNER_TEMP=str(workspace),
                               CAPHE_REQUIRED_REF="0" * 40 if wrong_ref else revision)
            if python_environment:
                environment.update(PYTHONHOME=str(workspace / 'non-python-home'), PYTHONPATH=str(candidate))
            if temp_alias:
                actual = workspace / 'canonical-temp'; actual.mkdir(mode=0o700)
                alias = workspace / 'temp-alias'; alias.symlink_to(actual, target_is_directory=True)
                environment['TMPDIR'] = str(alias)
            scripts = workflow_scripts() if run_candidate else workflow_scripts()[:1]
            results = [subprocess.run(["bash", "-c", script], cwd=candidate,
                                      env=environment, text=True, capture_output=True, timeout=15) for script in scripts]
            return results if run_candidate else results[0]

    def test_candidate_noop_runner_and_manifest_cannot_skip_required_failure(self):
        result = self.run_workflow(failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CANDIDATE NOOP", result.stdout)
        self.assertEqual(result.stdout.count("REQUIRED"), 4)

    def test_required_matrix_passes_against_unchanged_candidate(self):
        result = self.run_workflow()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("CANDIDATE NOOP", result.stdout)
        self.assertEqual(result.stdout.count("REQUIRED"), 4)

    def test_candidate_declared_required_command_cannot_be_skipped(self):
        results = self.run_workflow(candidate_required_failure=True, run_candidate=True)
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        self.assertEqual(results[0].stdout.count("REQUIRED"), 4)
        self.assertNotEqual(results[1].returncode, 0)
        self.assertIn("CANDIDATE REQUIRED", results[1].stdout)
        self.assertNotIn("CANDIDATE NOOP", results[1].stdout)

    def test_candidate_declared_required_command_runs_with_accepted_runner(self):
        results = self.run_workflow(candidate_required_success=True, run_candidate=True)
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        self.assertEqual(results[0].stdout.count("REQUIRED"), 4)
        self.assertEqual(results[1].returncode, 0, results[1].stdout + results[1].stderr)
        self.assertEqual(results[1].stdout.count("CANDIDATE REQUIRED"), 1)
        self.assertNotIn("CANDIDATE NOOP", results[1].stdout)

    def test_wrong_policy_revision_fails_before_execution(self):
        result = self.run_workflow(wrong_ref=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_passing_checks_cannot_leave_changed_candidate_source(self):
        results = self.run_workflow(mutation=True, run_candidate=True)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.count("REQUIRED"), 4)

    def test_replaced_check_scripts_and_trivial_tests_cannot_hide_broken_candidate_product(self):
        result = self.run_workflow(replaced_checks=True, product_bad=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('broken', result.stdout + result.stderr)

    def test_retained_and_added_candidate_tests_run_in_separate_matrices(self):
        results = self.run_workflow(replaced_checks=True, new_candidate_failure=True, run_candidate=True)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        self.assertNotEqual(results[1].returncode, 0)
        self.assertIn('candidate added test ran', results[1].stdout + results[1].stderr)

    def test_candidate_matrix_remains_available_after_retained_failure(self):
        results = self.run_workflow(replaced_checks=True, product_bad=True, run_candidate=True)
        self.assertEqual(len(results), 2)
        self.assertNotEqual(results[0].returncode, 0)
        self.assertEqual(results[1].returncode, 0, results[1].stdout + results[1].stderr)
        self.assertIn('if: ${{ !cancelled() }}', (ROOT / '.github/workflows/quality.yml').read_text())

    def test_passing_checks_cannot_leave_changed_retained_harness(self):
        result = self.run_workflow(mutation='harness')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count('REQUIRED'), 4)

    def test_both_matrices_use_canonical_temp_paths(self):
        results = self.run_workflow(temp_alias=True, run_candidate=True)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count('REQUIRED'), 4)

    def test_candidate_stdlib_shadow_cannot_skip_either_python_matrix(self):
        results = self.run_workflow(replaced_checks=True, product_bad=True, shadow_runner=True,
                                    new_candidate_failure=True, run_candidate=True)
        for result in results:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('SHADOWED STDLIB RUNNER', result.stdout + result.stderr)
        self.assertIn('broken', results[0].stdout + results[0].stderr)
        self.assertIn('candidate added test ran', results[1].stdout + results[1].stderr)

    def test_both_matrices_clear_inherited_python_import_configuration(self):
        results = self.run_workflow(python_environment=True, candidate_required_success=True, run_candidate=True)
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        self.assertEqual(results[0].stdout.count('REQUIRED'), 4)
        self.assertEqual(results[1].returncode, 0, results[1].stdout + results[1].stderr)
        self.assertEqual(results[1].stdout.count('CANDIDATE REQUIRED'), 1)
