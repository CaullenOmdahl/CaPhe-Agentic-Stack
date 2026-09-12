#!/usr/bin/env python3
"""Read-only diagnostics: compare Git's effective hook and gate to the selected runtime."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

HOOK_FILES = ("pre-commit", "strict-green-gate.sh", "strict_gate.py")


def _installer():
    spec = importlib.util.spec_from_file_location("caphe_install_doctor", Path(__file__).with_name("stack_install.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_digest(root):
    module = _installer()
    try:
        return module._digest(root)
    except (module.InstallError, OSError, ValueError):
        return None


def find_duplicate_skills(roots):
    found = {}
    for root in roots:
        if not root.is_dir():
            continue
        for skill in root.iterdir():
            if (skill / "SKILL.md").is_file():
                found.setdefault(skill.name, []).append(str(skill))
    return {name: locations for name, locations in found.items() if len(locations) > 1}


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, env=_installer()._git_env())
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _safe_digest(path):
    if not path or not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(repo, *, runtime, git_config=None):
    repo, runtime = Path(repo).absolute(), Path(runtime).absolute()
    unresolved = []
    if not runtime.is_dir():
        unresolved.append("runtime_missing")
    version_file = runtime / "VERSION"
    version = version_file.read_text().strip() if _safe_digest(version_file) else None
    if version not in (None, "1", "2", "3"):
        version = "invalid"
    if (runtime / ".caphe-runtime.json").exists() and version != "3":
        unresolved.append("runtime_version_mismatch")
    config = git_config or (lambda key: _git(repo, "config", "--get", key))
    hook_path = config("core.hooksPath")
    if git_config:
        hookdir = Path(hook_path) if hook_path else None
    else:
        effective = _git(repo, "rev-parse", "--git-path", "hooks")
        hookdir = Path(effective) if effective else None
    if hookdir and not hookdir.is_absolute():
        hookdir = repo / hookdir
    comparisons = {}
    for name in HOOK_FILES:
        actual = _safe_digest(hookdir / name) if hookdir else None
        expected = _safe_digest(runtime / "strict-mode/bin" / name)
        comparisons[name] = {"actual": actual, "expected": expected, "matches": bool(actual and expected and actual == expected)}
    verified = all(item["matches"] for item in comparisons.values()) and all(os.access(hookdir / name, os.X_OK) for name in HOOK_FILES[:2])
    marker = repo / ".agent/.strict-version"
    marked = bool(_safe_digest(marker))
    marker_version = marker.read_text().strip() if marked else None
    if marker_version not in (None, "1", "2", "3"):
        marker_version = "invalid"
    if not verified:
        unresolved.append("effective_gate_mismatch")
    if marked and marker_version != "3":
        unresolved.append("project_version_mismatch")
    digest = tree_digest(runtime) if runtime.is_dir() else None
    if runtime.is_dir() and digest is None:
        unresolved.append("runtime_inventory_invalid")
    result = {
        "runtime": {"path": str(runtime), "version": version, "source_digest": digest},
        "hooks": {"effective_path": str(hookdir) if hookdir else None, "configured": hook_path is not None, "verified": verified, "files": comparisons, "hook_digest": comparisons["pre-commit"]["actual"], "gate_digest": comparisons["strict-green-gate.sh"]["actual"]},
        "project": {"path": str(repo), "managed": bool(marked and marker_version == "3" and verified), "marker_present": marked, "managed_version": marker_version},
        "duplicate_skills": find_duplicate_skills([runtime / "skills", repo / ".codex/skills", repo / ".claude/skills"]),
        "unresolved": unresolved,
    }
    if result["duplicate_skills"]:
        unresolved.append("duplicate_skills")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--runtime", required=True)
    args = parser.parse_args(argv)
    result = inspect(args.repo, runtime=args.runtime)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
