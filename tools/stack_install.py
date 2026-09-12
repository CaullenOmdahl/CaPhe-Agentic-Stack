#!/usr/bin/env python3
"""Plan, apply and verify an explicitly inventoried public runtime. Never auto-apply."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile


class InstallError(RuntimeError):
    pass


_RUNTIME_DIRS = ("tools", "skills", "strict-mode", "schemas")
_SUPPORT_DOCS = ("docs/efficiency-runtime.md", "docs/review-workflow.md", "docs/canon.md")
_BOOTSTRAP = ("tools/stack_install.py", "tools/stack_doctor.py", "tools/stack_prepare.py", "strict-mode/bin/strict_init.py")
_MANIFEST = ".caphe-runtime.json"


def _git_env():
    """Keep user/global configuration while removing the caller's repository selection."""
    local = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
        "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
    }
    return {key: value for key, value in os.environ.items()
            if key not in local and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}


def _safe_path(value):
    if not isinstance(value, (str, Path)):
        raise InstallError("path must be a string")
    path = Path(os.path.abspath(Path(value).expanduser()))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise InstallError("symlink path is unsafe: " + str(part))
    return path


def _public(rel):
    if not isinstance(rel, str):
        return False
    path = PurePosixPath(rel)
    denied = {"__pycache__", "node_modules", "private", "secrets", "credentials", "cache", "caches"}
    return (not path.is_absolute() and len(path.parts) > 1 and (path.parts[0] in _RUNTIME_DIRS or rel in _SUPPORT_DOCS)
            and path.as_posix() == rel and not any(p.startswith(".") or p.lower() in denied for p in path.parts)
            and path.suffix not in {".pyc", ".pyo", ".pem", ".key"})


def _file_entry(root, rel):
    if not _public(rel):
        raise InstallError("non-public payload path: " + str(rel))
    path = _safe_path(root / rel)
    if not path.is_file():
        raise InstallError("payload must be a regular file: " + rel)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o7000:
        raise InstallError("special permission bits in payload")
    return [rel, hashlib.sha256(path.read_bytes()).hexdigest(), mode]


def _payload(root):
    root = _safe_path(root)
    # Git identifies public distribution files, but bytes come from the dirty worktree.
    # A deployed standalone runtime carries the same closed inventory in its manifest.
    manifest = root / _MANIFEST
    expected = None
    git = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True, env=_git_env())
    if git.returncode == 0 and Path(git.stdout.strip()).resolve() == root:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *_RUNTIME_DIRS, *_SUPPORT_DOCS], capture_output=True, check=True, env=_git_env())
        names = set(result.stdout.decode().split("\0")) - {""}
        names.update(rel for rel in _BOOTSTRAP if (root / rel).exists())
        names = {name for name in names if _public(name)}
    elif manifest.is_file() and not manifest.is_symlink():
        try:
            data = json.loads(manifest.read_text())
            expected = data["payload"]
            names = [entry[0] for entry in expected]
            if len(names) != len(set(names)):
                raise ValueError("duplicate names")
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise InstallError("invalid runtime inventory") from error
    else:
        raise InstallError("source must be a Git distribution root or an inventoried runtime")
    entries = [_file_entry(root, rel) for rel in sorted(names)]
    if expected is not None and (entries != expected or _entries_digest(entries) != data.get("source_digest")):
        raise InstallError("runtime differs from its public inventory")
    for required in ("tools", "skills", "strict-mode"):
        if not any(item[0].startswith(required + "/") for item in entries):
            raise InstallError("missing public runtime directory: " + required)
    return entries


def _entries_digest(entries):
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def _digest(root):
    return _entries_digest(_payload(root))


def _outside_git(path):
    for ancestor in (path, *path.parents):
        if (ancestor / ".git").exists() or (ancestor / ".git").is_symlink():
            raise InstallError("runtime and private inventory must be outside Git worktrees")
        if ancestor.exists():
            result = subprocess.run(["git", "-C", str(ancestor), "rev-parse", "--git-dir"], capture_output=True, env=_git_env())
            if result.returncode == 0:
                raise InstallError("runtime and private inventory must be outside Git repositories")
            break


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _private_preflight(path, source, target):
    path = _safe_path(path)
    _outside_git(path)
    if _overlap(path, source) or _overlap(path, target):
        raise InstallError("private inventory overlaps source or target")
    for protected in (Path.home() / ".codex/memories", Path.home() / ".codex/sessions"):
        if _overlap(path, protected):
            raise InstallError("private inventory overlaps canonical memory")
    if path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise InstallError("existing private inventory must already be owner-only")
    return path


def plan_runtime_install(source, target):
    source, target = _safe_path(source), _safe_path(target)
    if _overlap(source, target):
        raise InstallError("runtime target must be outside source checkout")
    _outside_git(target)
    payload = _payload(source)
    return {"action": "install-runtime", "source": str(source), "target": str(target), "source_digest": _entries_digest(payload), "payload": payload}


def _validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"action", "source", "target", "source_digest", "payload"}:
        raise InstallError("unsupported plan")
    if not all(isinstance(plan[key], str) for key in ("action", "source", "target", "source_digest")) or not isinstance(plan["payload"], list):
        raise InstallError("invalid plan types")
    expected = plan_runtime_install(plan["source"], plan["target"])
    if plan != expected:
        raise InstallError("plan does not match current public source inventory")
    return Path(plan["source"]), Path(plan["target"])


def verify_runtime_plan(plan):
    """Verify only managed files; unrelated local files and secrets remain untouched."""
    _, target = _validate_plan(plan)
    return [_file_entry(target, item[0]) for item in plan["payload"]] == plan["payload"]


def apply_runtime_plan(plan, *, inventory_root, fail_after=None):
    source, target = _validate_plan(plan)
    inventory = _private_preflight(inventory_root, source, target)
    destinations = [target / item[0] for item in plan["payload"]] + [target / _MANIFEST, target / "VERSION"]
    receipt_path = inventory / ("runtime-" + plan["source_digest"][:16] + ".json")
    for destination in destinations + [receipt_path]:
        _safe_path(destination)
        if destination.exists() and not destination.is_file():
            raise InstallError("destination is not a regular file: " + str(destination))
        if any(parent.exists() and not parent.is_dir() for parent in destination.parents):
            raise InstallError("destination parent is not a directory")
    created = []
    def mkdir(path, mode=0o755):
        if path.exists():
            return
        mkdir(path.parent, mode)
        path.mkdir(mode=mode)
        created.append(path)
    mkdir(inventory, 0o700)
    stage = Path(tempfile.mkdtemp(prefix="caphe-stage-", dir=inventory))
    journal = []
    try:
        for rel, _, _ in plan["payload"]:
            staged = stage / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, staged, follow_symlinks=False)
        if [_file_entry(stage, item[0]) for item in plan["payload"]] != plan["payload"]:
            raise InstallError("source changed while staging")
        (stage / "VERSION").write_text("3\n")
        (stage / _MANIFEST).write_text(json.dumps({"payload": plan["payload"], "source_digest": plan["source_digest"]}, sort_keys=True) + "\n")
        receipt = {"action": "install-runtime", "source_digest": plan["source_digest"], "target": str(target), "verified": True}
        def write(destination, data, mode):
            _safe_path(destination)
            previous = (destination.read_bytes(), stat.S_IMODE(destination.stat().st_mode)) if destination.exists() else None
            journal.append((destination, previous))
            mkdir(destination.parent)
            fd, name = tempfile.mkstemp(prefix=".caphe-write-", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.chmod(name, mode)
                os.replace(name, destination)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        for index, destination in enumerate(destinations[:-1], 1):
            staged = stage / destination.relative_to(target)
            write(destination, staged.read_bytes(), stat.S_IMODE(staged.stat().st_mode))
            if fail_after == index:
                raise InstallError("injected partial install failure")
        if _payload(target) != plan["payload"]:
            raise InstallError("deployed runtime verification failed")
        # VERSION is the final runtime activation write, after manifest and byte checks.
        write(target / "VERSION", (stage / "VERSION").read_bytes(), 0o644)
        if fail_after == len(destinations):
            raise InstallError("injected activation failure")
        write(receipt_path, (json.dumps(receipt, sort_keys=True) + "\n").encode(), 0o600)
        if fail_after == len(destinations) + 1:
            raise InstallError("injected receipt failure")
        return receipt
    except BaseException:
        for destination, previous in reversed(journal):
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(previous[0])
                destination.chmod(previous[1])
        raise
    finally:
        shutil.rmtree(stage)
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass


def initialize_project(source, repo, *, apply=False):
    source, repo = _safe_path(source), _safe_path(repo)
    disabled = repo / ".agent" / ".strict-mode"
    _safe_path(disabled)
    if disabled.is_file() and disabled.read_bytes().partition(b"\n")[0] == b"off":
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", ".agent/.strict-mode"], capture_output=True, env=_git_env()).returncode == 0
        if not tracked:
            return {"state": "disabled", "changed": False}
    result = {"state": "planned", "changed": False, "source_digest": _digest(source)}
    if apply:
        init = source / "strict-mode" / "bin" / "strict-init.sh"
        if not init.is_file():
            raise InstallError("runtime strict-init is unavailable")
        run = subprocess.run(["bash", str(init)], cwd=repo, env={**_git_env(), "STRICT_MODE_CANON": str(source / "strict-mode")}, text=True, capture_output=True)
        if run.returncode:
            raise InstallError("strict-init activation failed: " + run.stderr.strip())
        import importlib.util
        spec = importlib.util.spec_from_file_location("caphe_doctor", Path(__file__).with_name("stack_doctor.py"))
        doctor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(doctor)
        report = doctor.inspect(repo, runtime=source)
        if not report["hooks"].get("verified") or not report["project"].get("managed"):
            raise InstallError("strict-init effective hook verification failed")
        result.update(state="initialized", changed=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", default="~/.local/share/caphe/runtime")
    parser.add_argument("--inventory-root")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    plan = plan_runtime_install(args.source, args.target)
    if args.apply and not args.inventory_root:
        parser.error("--inventory-root is required with --apply")
    print(json.dumps(apply_runtime_plan(plan, inventory_root=args.inventory_root) if args.apply else plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
