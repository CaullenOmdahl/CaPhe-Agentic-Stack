#!/usr/bin/env python3
"""Plan, apply and verify an explicitly inventoried public runtime. Never auto-apply."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile


class InstallError(RuntimeError):
    pass


_RUNTIME_DIRS = ("tools", "skills", "strict-mode", "schemas")
_SUPPORT_DOCS = ("docs/efficiency-runtime.md", "docs/review-workflow.md", "docs/canon.md")
_MANIFEST = ".caphe-runtime.json"


def _git_env():
    """Preserve deliberate user config choices, not inherited Git discovery/state."""
    user_config = {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}
    return {key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") or key in user_config}


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
    ancestors = (path, *path.parents)
    # Physical worktree markers must be checked even when Git cannot load config.
    for ancestor in ancestors:
        if (ancestor / ".git").exists() or (ancestor / ".git").is_symlink():
            raise InstallError("runtime and private inventory must be outside Git worktrees")
    nearest = next(ancestor for ancestor in ancestors if ancestor.exists())
    try:
        result = subprocess.run(["git", "-C", str(nearest), "rev-parse", "--git-dir"],
                                capture_output=True, env={**_git_env(), "LC_ALL": "C"})
    except OSError as error:
        raise InstallError("Git repository boundary could not be verified") from error
    if result.returncode == 0:
        raise InstallError("runtime and private inventory must be outside Git repositories")
    ordinary_nonrepo = result.stderr == b"fatal: not a git repository (or any of the parent directories): .git\n"
    filesystem_boundary = re.fullmatch(
        rb"fatal: not a git repository \(or any parent up to mount point [^\n]+\)\n"
        rb"Stopping at filesystem boundary \(GIT_DISCOVERY_ACROSS_FILESYSTEM not set\)\.\n", result.stderr)
    if result.returncode != 128 or not (ordinary_nonrepo or filesystem_boundary):
        raise InstallError("Git repository boundary could not be verified")


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
    previous = _payload(target) if (target / _MANIFEST).exists() else []
    return {"action": "install-runtime", "source": str(source), "target": str(target), "source_digest": _entries_digest(payload), "payload": payload, "previous_payload": previous}


def _retired_remaining(target, previous, payload):
    names = [item[0] for item in payload]
    return any(path.exists() and not (path.is_dir() and any(name.startswith(item[0] + "/") for name in names))
               for item in previous if item[0] not in names
               for path in [_safe_path(target / item[0])])


def _manifest_bytes(payload):
    return (json.dumps({"payload": payload, "source_digest": _entries_digest(payload)}, sort_keys=True) + "\n").encode()


def _metadata_matches(target, payload):
    for name, content in ((_MANIFEST, _manifest_bytes(payload)), ("VERSION", b"3\n")):
        path = target / name
        if (path.is_symlink() or not path.is_file() or path.read_bytes() != content
                or stat.S_IMODE(path.stat().st_mode) != 0o644):
            return False
    return True


def _validate_plan(plan, *, after_install=False):
    if not isinstance(plan, dict) or set(plan) != {"action", "source", "target", "source_digest", "payload", "previous_payload"}:
        raise InstallError("unsupported plan")
    if not all(isinstance(plan[key], str) for key in ("action", "source", "target", "source_digest")) or not isinstance(plan["payload"], list):
        raise InstallError("invalid plan types")
    previous = plan["previous_payload"]
    if not isinstance(previous, list) or any(
            not isinstance(entry, list) or len(entry) != 3 or not _public(entry[0])
            or not isinstance(entry[1], str) or not re.fullmatch(r"[0-9a-f]{64}", entry[1])
            or type(entry[2]) is not int or not 0 <= entry[2] <= 0o777
            for entry in previous):
        raise InstallError("invalid prior payload inventory")
    if [entry[0] for entry in previous] != sorted({entry[0] for entry in previous}):
        raise InstallError("prior inventory must be sorted and unique")
    expected = plan_runtime_install(plan["source"], plan["target"])
    already_applied = expected["previous_payload"] == plan["payload"] and not _retired_remaining(Path(plan["target"]), previous, plan["payload"])
    if after_install or already_applied:
        expected["previous_payload"] = previous
    if plan != expected:
        raise InstallError("plan does not match current public source inventory")
    return Path(plan["source"]), Path(plan["target"])


def verify_runtime_plan(plan):
    """Verify only managed files; unrelated local files and secrets remain untouched."""
    _, target = _validate_plan(plan, after_install=True)
    return ([_file_entry(target, item[0]) for item in plan["payload"]] == plan["payload"]
            and not _retired_remaining(target, plan["previous_payload"], plan["payload"])
            and _metadata_matches(target, plan["payload"]))


def runtime_receipt_path(inventory, source_digest, target):
    """Each canonical target has its own immutable receipt for a source payload.

    Legacy source-only receipts are left untouched; they cannot name multiple
    targets and are not adopted as ownership claims for this namespace.
    """
    identity = json.dumps([source_digest, str(_safe_path(target))], separators=(",", ":"))
    key = hashlib.sha256(identity.encode()).hexdigest()
    return Path(inventory) / ("runtime-" + key + ".json")


def apply_runtime_plan(plan, *, inventory_root, fail_after=None):
    source, target = _validate_plan(plan)
    inventory = _private_preflight(inventory_root, source, target)
    destinations = [target / item[0] for item in plan["payload"]] + [target / _MANIFEST, target / "VERSION"]
    current = {item[0] for item in plan["payload"]}
    retired = [item for item in plan["previous_payload"] if item[0] not in current]
    receipt_path = runtime_receipt_path(inventory, plan["source_digest"], target)
    installed = _payload(target) if (target / _MANIFEST).exists() else []
    owned = {item[0] for item in installed}
    removing = {item[0] for item in retired if item[0] in owned}
    removed_dirs = set()
    # A prior verified inventory authorizes only its files and directories needed
    # to contain them. Even an unrelated empty directory blocks replacement.
    for destination in destinations:
        _safe_path(destination)
        rel = destination.relative_to(target).as_posix()
        if destination.is_dir():
            descendants = {name for name in removing if name.startswith(rel + "/")}
            allowed_dirs = {parent for name in descendants for parent in (target / name).parents if parent == destination or destination in parent.parents}
            if not descendants:
                raise InstallError("unowned destination directory: " + str(destination))
            for child in (destination, *destination.rglob("*")):
                _safe_path(child)
                if child.is_dir() and child in allowed_dirs:
                    removed_dirs.add(child)
                elif not child.is_file() or child.relative_to(target).as_posix() not in descendants:
                    raise InstallError("unmanaged child blocks directory replacement: " + str(child))
        elif destination.exists():
            if not destination.is_file():
                raise InstallError("destination is not a regular file: " + str(destination))
            if rel not in owned and not (installed and rel in (_MANIFEST, "VERSION")):
                raise InstallError("unowned destination file: " + str(destination))
        for parent in destination.parents:
            if parent.exists() and not parent.is_dir() and (parent == target or target not in parent.parents or parent.relative_to(target).as_posix() not in removing):
                raise InstallError("unmanaged destination parent is not a directory")
    if installed and not _metadata_matches(target, installed):
        raise InstallError("runtime metadata differs from installed format")
    receipt = {"action": "install-runtime", "source_digest": plan["source_digest"], "target": str(target), "verified": True, "retired_files": [item[0] for item in retired]}
    receipt_data = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    _safe_path(receipt_path)
    if receipt_path.exists():
        if not receipt_path.is_file():
            raise InstallError("private receipt must be a regular file")
        try:
            receipt_bytes = receipt_path.read_bytes()
            existing = json.loads(receipt_bytes)
            known = (isinstance(existing, dict) and set(existing) == set(receipt)
                     and all(existing[key] == receipt[key] for key in receipt if key != "retired_files")
                     and existing["verified"] is True and isinstance(existing["retired_files"], list)
                     and all(_public(name) for name in existing["retired_files"])
                     and existing["retired_files"] == sorted(set(existing["retired_files"]))
                     and installed == plan["payload"]
                     and receipt_bytes == (json.dumps(existing, sort_keys=True) + "\n").encode())
            if stat.S_IMODE(receipt_path.stat().st_mode) != 0o600 or (receipt_bytes != receipt_data and not known):
                raise ValueError("unowned receipt")
        except (ValueError, TypeError, OSError) as error:
            raise InstallError("private receipt collision") from error
    if any(parent.exists() and not parent.is_dir() for parent in receipt_path.parents):
        raise InstallError("private receipt parent is not a directory")
    created = []
    journal = []
    def mkdir(path, mode=0o755):
        if path.exists():
            return
        mkdir(path.parent, mode)
        path.mkdir(mode=mode)
        created.append(path)
        journal.append(("created-directory", path, None))
    mkdir(inventory, 0o700)
    stage = Path(tempfile.mkdtemp(prefix="caphe-stage-", dir=inventory))
    # Inventory ancestors contain staging until finally; only target mutations
    # belong in the reverse journal. Empty inventory ancestors are cleaned last.
    journal.clear()
    try:
        for rel, _, _ in plan["payload"]:
            staged = stage / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, staged, follow_symlinks=False)
        if [_file_entry(stage, item[0]) for item in plan["payload"]] != plan["payload"]:
            raise InstallError("source changed while staging")
        # Retire only the verified current files, never a replacement directory
        # occupying an old filename on an idempotent repeat.
        for item in retired:
            if item[0] not in removing:
                continue
            destination = target / item[0]
            if _file_entry(target, item[0]) != item:
                raise InstallError("retired managed file changed before removal")
            journal.append(("file", destination, (destination.read_bytes(), item[2])))
            destination.unlink()
        for directory in sorted(removed_dirs, key=lambda path: len(path.parts), reverse=True):
            mode = stat.S_IMODE(directory.stat().st_mode)
            directory.rmdir()
            journal.append(("removed-directory", directory, mode))
        (stage / "VERSION").write_text("3\n")
        (stage / _MANIFEST).write_bytes(_manifest_bytes(plan["payload"]))
        (stage / _MANIFEST).chmod(0o644)
        def write(destination, data, mode):
            _safe_path(destination)
            previous = (destination.read_bytes(), stat.S_IMODE(destination.stat().st_mode)) if destination.exists() else None
            mkdir(destination.parent)
            journal.append(("file", destination, previous))
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
        if not receipt_path.exists():
            write(receipt_path, receipt_data, 0o600)
        if fail_after == len(destinations) + 1:
            raise InstallError("injected receipt failure")
        return receipt
    except BaseException:
        for kind, destination, previous in reversed(journal):
            if kind == "created-directory":
                destination.rmdir()
            elif kind == "removed-directory":
                destination.mkdir(mode=previous)
                destination.chmod(previous)
            elif previous is None:
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
    try:
        probe = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, timeout=30,
                               env={**_git_env(), "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        raise InstallError("project Git root probe could not complete") from None
    if probe.returncode == 0 and probe.stdout.strip():
        repo = _safe_path(probe.stdout.removesuffix("\n"))
    elif not (probe.returncode == 128 and "not a git repository" in probe.stderr
              and not any((parent / ".git").exists() or (parent / ".git").is_symlink()
                          for parent in (repo, *repo.parents))):
        raise InstallError("project Git root could not be verified")
    # Existing ordinary non-Git directories still support planning and explicit disable.
    disabled = repo / ".agent" / ".strict-mode"
    _safe_path(disabled)
    if disabled.is_file() and disabled.read_bytes().partition(b"\n")[0] == b"off":
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", ".agent/.strict-mode"], capture_output=True, env=_git_env()).returncode == 0
        if not tracked:
            return {"state": "disabled", "changed": False}
    result = {"state": "planned", "changed": False, "source_digest": _digest(source)}
    if apply:
        if probe.returncode != 0:
            raise InstallError("project activation requires a Git worktree")
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
