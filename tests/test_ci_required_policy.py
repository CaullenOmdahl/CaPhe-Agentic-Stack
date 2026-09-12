"""Run the actual workflow shell against separate candidate and accepted-policy fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def workflow_script():
    lines = (ROOT / ".github/workflows/quality.yml").read_text().splitlines()
    start = lines.index("        run: |") + 1
    result = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        result.append(line[10:])
    return "\n".join(result) + "\n"


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
    def run_workflow(self, *, failure=False, mutation=False, wrong_ref=False):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            candidate = workspace / "candidate"; candidate.mkdir()
            policy = workspace / "required-policy"; policy.mkdir()
            for root in (candidate, policy):
                (root / "strict-mode/bin").mkdir(parents=True)
                (root / ".agent").mkdir()
            # Either candidate file would make the former single-step workflow falsely pass.
            (candidate / "strict-mode/bin/strict_gate.py").write_text("print('CANDIDATE NOOP')\n")
            (candidate / ".agent/strict-gate.json").write_text(json.dumps({"commands": []}))
            (candidate / "source.txt").write_text("original\n")
            commit(candidate)
            # The fixture runner deliberately has no source guard: the workflow must supply it.
            (policy / "strict-mode/bin/strict_gate.py").write_text(
                "import argparse,json,subprocess,sys\n"
                "p=argparse.ArgumentParser();p.add_argument('--manifest');p.add_argument('--mode');a=p.parse_args()\n"
                "assert a.mode=='completion'\n"
                "commands=json.load(open(a.manifest))['commands']\n"
                "codes=[subprocess.run(command).returncode for command in commands]\n"
                "sys.exit(any(codes))\n")
            commands = [["python3", "-c", f"print('REQUIRED {i}')"] for i in range(4)]
            if failure:
                commands[1][-1] += "; raise SystemExit(7)"
            if mutation:
                commands[1][-1] += "; from pathlib import Path; Path('source.txt').write_text('changed')"
            (policy / ".agent/strict-gate.json").write_text(json.dumps({"commands": commands}))
            revision = commit(policy)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            environment.update(GITHUB_WORKSPACE=str(workspace), CAPHE_REQUIRED_REF="0" * 40 if wrong_ref else revision)
            return subprocess.run(["bash", "-c", workflow_script()], cwd=candidate,
                                  env=environment, text=True, capture_output=True, timeout=15)

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

    def test_wrong_policy_revision_fails_before_execution(self):
        result = self.run_workflow(wrong_ref=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_passing_checks_cannot_leave_changed_candidate_source(self):
        result = self.run_workflow(mutation=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("REQUIRED"), 4)
