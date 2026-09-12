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
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True,
                                env=_installer()._git_env(), timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _safe_digest(path):
    if not path or not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(path):
    if not _safe_digest(path):
        return None
    return {b"1": "1", b"2": "2", b"3": "3"}.get(path.read_bytes().strip(), "invalid")


def _instructions(repo, runtime):
    begin = b"<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->"
    end = b"<!-- STRICT-MODE:END -->"
    template = runtime / "strict-mode/templates/instruction-section.md"
    expected = template.read_bytes().strip(b"\n") if _safe_digest(template) else None
    comparisons = {}
    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        section = None
        try:
            path = (repo / name).resolve(strict=True)
            path.relative_to(repo.resolve())
            if _safe_digest(path):
                lines = path.read_bytes().splitlines(keepends=True)
                starts = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == begin]
                ends = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == end]
                if len(starts) == len(ends) == 1 and starts[0] < ends[0]:
                    section = b"".join(lines[starts[0]:ends[0] + 1]).strip(b"\n")
        except (OSError, ValueError, RuntimeError):
            pass
        comparisons[name] = {"matches": bool(expected and section == expected),
                             "sha256": hashlib.sha256(section).hexdigest() if section else None}
    return {"verified": all(item["matches"] for item in comparisons.values()), "files": comparisons}


def _chain_status(repo, hookdir, runtime):
    if hookdir is None:
        return {"verified": False, "reason": "effective hook directory is missing"}
    try:
        # Use the doctor's bundled validator, never execute a target chain or metadata.
        path = Path(__file__).parents[1] / "strict-mode/bin/strict_init.py"
        spec = importlib.util.spec_from_file_location("caphe_activation_doctor", path)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        record = validator.read_activation(repo, hookdir, canon=runtime / "strict-mode")
        return {"verified": True, "chain_sha256": record["chain_sha256"], "original_hook_present": record["previous_hook"] is not None,
                "forwarded_hook_count": len(record.get("forwarded_hooks", {}))}
    except (OSError, ValueError, RuntimeError) as error:
        return {"verified": False, "reason": str(error)}


def inspect(repo, *, runtime, git_config=None):
    repo, runtime = Path(repo).absolute(), Path(runtime).absolute()
    unresolved = []
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top:
        repo = Path(top).absolute()
    else:
        unresolved.append("project_not_git")
    if not runtime.is_dir():
        unresolved.append("runtime_missing")
    version_file = runtime / "VERSION"
    version = _version(version_file)
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
    chain = _chain_status(repo, hookdir, runtime)
    if not chain["verified"]:
        unresolved.append("hook_chain_mismatch")
    verified = verified and chain["verified"]
    marker = repo / ".agent/.strict-version"
    marker_version = _version(marker)
    marked = marker_version is not None
    if not verified:
        unresolved.append("effective_gate_mismatch")
    if not marked:
        unresolved.append("project_version_missing")
    if marked and marker_version != "3":
        unresolved.append("project_version_mismatch")
    instructions = _instructions(repo, runtime)
    if not instructions["verified"]:
        unresolved.append("managed_instructions_mismatch")
    digest = tree_digest(runtime) if runtime.is_dir() else None
    if runtime.is_dir() and digest is None:
        unresolved.append("runtime_inventory_invalid")
    result = {
        "runtime": {"path": str(runtime), "version": version, "source_digest": digest},
        "hooks": {"effective_path": str(hookdir) if hookdir else None, "configured": hook_path is not None, "verified": verified, "chain": chain, "files": comparisons, "hook_digest": comparisons["pre-commit"]["actual"], "gate_digest": comparisons["strict-green-gate.sh"]["actual"]},
        "project": {"path": str(repo), "managed": bool(top and marked and marker_version == "3" and verified and instructions["verified"]), "marker_present": marked, "managed_version": marker_version},
        "instructions": instructions,
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
