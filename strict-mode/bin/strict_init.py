#!/usr/bin/env python3
"""Transactional Strict Mode initialization, including worktree-aware hook activation."""
import importlib.util
import hashlib
import re
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile

BEGIN = "<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->"
END = "<!-- STRICT-MODE:END -->"
HOOK_FILES = ("pre-commit", "strict-green-gate.sh", "strict_gate.py")
FORWARDED_HOOKS = {"applypatch-msg", "pre-applypatch", "post-applypatch", "pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push", "pre-receive", "update", "proc-receive", "post-receive", "post-update", "reference-transaction", "push-to-checkout", "pre-auto-gc", "post-rewrite", "sendemail-validate", "fsmonitor-watchman", "p4-changelist", "p4-prepare-changelist", "p4-post-changelist", "p4-pre-submit", "post-index-change"}
RECEIVE_SENSITIVE_HOOKS = {"pre-receive", "update", "post-receive", "post-update", "push-to-checkout", "proc-receive", "reference-transaction"}
CHAIN_FILE = ".caphe-chain.sh"
ACTIVATION_FILE = ".caphe-activation.json"
# Exact historical framework wrappers; custom variants must still be chained.
LEGACY_WRAPPER_SHA256 = "ed90b0ef03c5ba58a9f4d52dea16b0aa67d960bac70893213275f59cbba18a64"
LEGACY_WRAPPER_HASHES = frozenset({
    LEGACY_WRAPPER_SHA256,
    # v2 strict-init.sh copied this exact canonical bin/pre-commit at 4e9c057.
    "13590f12c84d51af7d3b461e1c3dc5cb441ed8aab3d600786fbc62d681cc38bd",
})


class InitError(RuntimeError):
    pass


# This entry point is also distributed alone as ~/strict-mode.
def _git_env():
    """Keep global config choices; discard inherited discovery and repository overrides."""
    allowed = {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}
    return {key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") or key in allowed}


def git(root, *args, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, env=_git_env())
    if check and result.returncode:
        raise InitError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip() if result.returncode == 0 else None


def _repository_root(root):
    environment = _git_env()
    environment["LC_ALL"] = "C"
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                            text=True, capture_output=True, env=environment)
    if result.returncode == 0:
        return result.stdout.strip()
    markers = any((parent / ".git").exists() or (parent / ".git").is_symlink()
                  for parent in (root, *root.parents))
    if not markers and result.returncode == 128 and result.stderr.startswith("fatal: not a git repository (or any"):
        return None
    raise InitError("Git repository discovery failed: " + result.stderr.strip())


def safe(path):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise InitError("unsafe destination symlink: " + str(component))
    if path.exists() and not path.is_file():
        raise InitError("destination must be a regular file: " + str(path))
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise InitError("destination parent must be a directory")


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _original_hook(root, hookdir, invocation, name="pre-commit"):
    if not isinstance(invocation, str) or not invocation or "\0" in invocation or Path(invocation).name != name:
        raise InitError("invalid original-hook invocation")
    path = Path(invocation)
    if name in RECEIVE_SENSITIVE_HOOKS and not path.is_absolute():
        raise InitError("receive-sensitive hook requires an absolute core.hooksPath; "
                        "select the original hook directory with an absolute path and rerun initialization to reconcile")
    path = path if path.is_absolute() else root / path
    resolved = path.resolve(strict=True)
    if hookdir == resolved or hookdir in resolved.parents or not resolved.is_file() or not os.access(path, os.X_OK):
        raise InitError("original hook is missing, non-executable, or recursive")
    return {"path": invocation, "resolved": str(resolved), "sha256": _sha(path.read_bytes()),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def chain_bytes(previous):
    return ("CAPHE_PREVIOUS_HOOK=" + shlex.quote(previous["path"] if previous else "") + "\n").encode()


def forwarder_bytes(invocation):
    return ("#!/usr/bin/env bash\n" + shlex.quote(invocation) + ' "$@"\n').encode()


def activation_record(root, hookdir, canon, previous, forwarded=None, forwarded_targets=None):
    original = _original_hook(root, hookdir, previous) if previous else None
    if set(forwarded or {}) != set(forwarded_targets or {}):
        raise InitError("forwarded hook target identities missing; select the original hook directory to reconcile")
    return {"schema": 2, "source_files": {name: _sha((canon / "bin" / name).read_bytes()) for name in HOOK_FILES},
            "chain_sha256": _sha(chain_bytes(original)), "previous_hook": original,
            "forwarded_hooks": dict(forwarded or {}), "forwarded_targets": dict(forwarded_targets or {})}


def read_activation(root, hookdir, *, canon=None, verify_previous=True):
    """Detect local drift using declarative metadata; this is not signed attestation.

    No shell is sourced. A writer able to replace both metadata and managed files can
    manufacture a consistent record; independent source review remains necessary.
    """
    metadata, chain = hookdir / ACTIVATION_FILE, hookdir / CHAIN_FILE
    safe(metadata); safe(chain)
    if not metadata.is_file() or not chain.is_file():
        raise InitError("hook activation metadata or chain is missing")
    if metadata.stat().st_size > 65536 or chain.stat().st_size > 16384:
        raise InitError("hook activation record exceeds its size limit")
    def closed_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InitError("duplicate hook activation field")
            result[key] = value
        return result
    try:
        record = json.loads(metadata.read_text(), object_pairs_hook=closed_object)
    except (ValueError, UnicodeError) as error:
        raise InitError("malformed hook activation metadata") from error
    digest = lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    base_fields = {"schema", "source_files", "chain_sha256", "previous_hook"}
    schemas = {1: (base_fields, base_fields | {"forwarded_hooks"}),
               2: (base_fields | {"forwarded_hooks", "forwarded_targets"},)}
    if (not isinstance(record, dict) or type(record.get("schema")) is not int
            or record["schema"] not in schemas or set(record) not in schemas[record["schema"]]
            or not isinstance(record["source_files"], dict) or set(record["source_files"]) != set(HOOK_FILES)
            or not all(digest(value) for value in record["source_files"].values()) or not digest(record["chain_sha256"])):
        raise InitError("invalid hook activation schema")
    forwarded = record.get("forwarded_hooks", {})
    if (not isinstance(forwarded, dict) or not set(forwarded).issubset(FORWARDED_HOOKS)
            or not all(digest(value) for value in forwarded.values())):
        raise InitError("invalid forwarded-hook inventory")
    for name in sorted(FORWARDED_HOOKS - set(forwarded)):
        if os.access(hookdir / name, os.X_OK):
            raise InitError("unrecorded executable Git hook: " + name +
                            "; preserve and move it to the original hook directory before explicit reconciliation")
    for name, expected_hash in {**record["source_files"], **forwarded}.items():
        path = hookdir / name
        safe(path)
        if not path.is_file() or _sha(path.read_bytes()) != expected_hash or stat.S_IMODE(path.stat().st_mode) != 0o755:
            raise InitError("managed hook differs from activation inventory: " + name)
    def validate_target(target, name):
        if (not isinstance(target, dict) or set(target) != {"path", "resolved", "sha256", "mode"}
                or not isinstance(target["path"], str) or not target["path"] or "\0" in target["path"]
                or Path(target["path"]).name != name or not isinstance(target["resolved"], str)
                or not Path(target["resolved"]).is_absolute() or not digest(target["sha256"])
                or type(target["mode"]) is not int or not 0 <= target["mode"] <= 0o777):
            raise InitError("invalid original-hook record")
        if verify_previous:
            try:
                actual = _original_hook(root, hookdir, target["path"], name)
            except InitError:
                raise
            except (OSError, ValueError, RuntimeError) as error:
                raise InitError("original hook cannot be verified") from error
            if actual != target:
                raise InitError("original hook changed since activation")
    targets = record.get("forwarded_targets", {})
    if not isinstance(targets, dict) or (record["schema"] == 2 and set(targets) != set(forwarded)):
        raise InitError("invalid forwarded-hook target inventory")
    if record["schema"] == 1 and forwarded and verify_previous:
        raise InitError("legacy forwarded hook target identities missing; select the original hook directory to reconcile")
    for name, target in targets.items():
        validate_target(target, name)
        if (hookdir / name).read_bytes() != forwarder_bytes(target["path"]):
            raise InitError("forwarded hook wrapper differs from its recorded target")
    previous = record["previous_hook"]
    if previous is not None:
        validate_target(previous, "pre-commit")
    actual_chain = chain.read_bytes()
    if actual_chain != chain_bytes(previous) or _sha(actual_chain) != record["chain_sha256"]:
        raise InitError("hook chain differs from its declarative activation record")
    if canon is not None:
        expected = {name: _sha((canon / "bin" / name).read_bytes()) for name in HOOK_FILES}
        if record["source_files"] != expected:
            raise InitError("hook activation source differs from the selected runtime")
    return record


def markers(text):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise InitError("malformed or duplicate strict-mode markers")
    return starts[0], ends[0]


class Transaction:
    def __init__(self):
        self.before = {}
        self.created = []

    def remember(self, path):
        safe(path)
        if path not in self.before:
            self.before[path] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None

    def mkdir(self, path):
        if path.exists():
            return
        self.mkdir(path.parent)
        path.mkdir()
        self.created.append(path)

    def write(self, path, content, mode=None):
        self.remember(path)
        if mode is None:
            mode = self.before[path][1] if self.before[path] else 0o644
        self.mkdir(path.parent)
        fd, name = tempfile.mkstemp(prefix=".strict-init-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content.encode() if isinstance(content, str) else content)
            os.chmod(name, mode)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def remove(self, path):
        self.remember(path)
        path.unlink(missing_ok=True)

    def rollback(self):
        for path, previous in reversed(list(self.before.items())):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous[0])
                path.chmod(previous[1])
        for directory in reversed(self.created):
            try:
                directory.rmdir()
            except OSError:
                pass


def initialize(canon, root, *, fail_probe=False):
    canon, root = Path(canon).resolve(), Path(root).resolve()
    top = _repository_root(root)
    is_git = top is not None
    if is_git:
        root = Path(top).resolve()
    disabled = root / ".agent/.strict-mode"
    safe(disabled)
    if (disabled.is_file() and disabled.read_bytes().partition(b"\n")[0] == b"off"
            and git(root, "ls-files", "--error-unmatch", "--", ".agent/.strict-mode", check=False) is None):
        print("done. STRICT MODE remains disabled by .agent/.strict-mode")
        return
    sources = [canon / "templates" / name for name in ("instruction-section.md", "adr-template.md", "OWNERS.md", "dod-checklist.md", "abstraction-template.md")]
    sources += [canon / "bin" / name for name in (*HOOK_FILES, "strict_evidence.py")]
    for source in sources:
        safe(source)
        if not source.is_file() or not source.read_bytes():
            raise InitError("missing or unreadable required source: " + str(source))
    template = sources[0].read_text()
    if markers(template) is None:
        raise InitError("instruction template has malformed managed markers")
    writes = {}
    for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        path = root / name
        if path.is_symlink():
            try:
                path = path.resolve(strict=True)
                path.relative_to(root)
            except (OSError, ValueError) as error:
                raise InitError("instruction symlink target is missing or outside the repository") from error
        safe(path)
        text = path.read_bytes().decode("utf-8") if path.exists() else ""
        span = markers(text)
        if span:
            lines = text.splitlines(keepends=True)
            content = "".join(lines[:span[0]]) + template.rstrip("\n") + "\n" + "".join(lines[span[1] + 1:])
        else:
            content = text + ("\n" if text else "") + template.rstrip("\n") + "\n\n"
        writes[path] = content
    defaults = {
        ".agent/decisions/0000-adr-template.md": sources[1].read_text(),
        ".agent/OWNERS.md": sources[2].read_text(),
        ".agent/dod-checklist.md": sources[3].read_text(),
        ".agent/abstraction/TEMPLATE.md": sources[4].read_text(),
        ".agent/traceability.md": "# Traceability\n\n> Generated from `.agent/evidence/*.json`.\n",
        ".claude/settings.json": json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": shlex.quote(str(canon / "bin/strict-green-gate.sh")) + " --mode completion || true"}]}]}}, indent=2) + "\n",
    }
    for name, text in defaults.items():
        path = root / name
        safe(path)
        if not path.exists():
            writes[path] = text
    manifest = root / ".agent/strict-gate.json"
    safe(manifest)
    if is_git and not manifest.exists():
        spec = importlib.util.spec_from_file_location("caphe_init_gate", canon / "bin/strict_gate.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        writes[manifest] = json.dumps(module.discover_default_manifest(root), indent=2) + "\n"
    marker = root / ".agent/.strict-version"
    safe(marker)
    hookdir = None
    previous = None
    config_paths = []
    retired_hooks = set()
    if is_git:
        # Resolve Git's actual effective path, including global/relative hooksPath.
        def gitpath(*args):
            value = Path(git(root, "rev-parse", *args))
            return (value if value.is_absolute() else root / value).resolve()
        gitdir = gitpath("--git-dir")
        common = gitpath("--git-common-dir")
        hookdir = gitdir / "caphe-hooks"
        effective_value = Path(git(root, "rev-parse", "--git-path", "hooks"))
        effective = effective_value if effective_value.is_absolute() else root / effective_value
        # Receive hooks run from the Git directory; reference-transaction can run
        # in either context. Relative forwarders cannot preserve both meanings.
        if not effective_value.is_absolute():
            for directory in (effective, gitdir / effective_value):
                for name in sorted(RECEIVE_SENSITIVE_HOOKS):
                    original = directory / name
                    if original.is_file() and os.access(original, os.X_OK):
                        raise InitError("receive-sensitive hook requires an absolute core.hooksPath; "
                                        "select the original hook directory with an absolute path and "
                                        "rerun initialization to reconcile: " + str(original))
        chain = hookdir / CHAIN_FILE
        active = effective.resolve() == hookdir
        existing = None
        # An inactive namespace is not ours merely because its name is caphe-hooks.
        # On deliberate reconciliation, validate the managed files while allowing
        # the selected original custom hook to have an accepted update.
        if active or any((hookdir / name).exists() for name in (*HOOK_FILES, CHAIN_FILE, ACTIVATION_FILE)):
            existing = read_activation(root, hookdir, verify_previous=active)
        owned_forwarders = set(existing.get("forwarded_hooks", {})) if existing else set()
        # Inactive reconciliation follows only the explicitly selected original directory.
        forwarded = dict(existing.get("forwarded_hooks", {})) if active else {}
        forwarded_targets = dict(existing.get("forwarded_targets", {})) if active else {}
        if active:
            # Never adopt shell text from an unverified old chain during refresh.
            previous = existing["previous_hook"]["path"] if existing["previous_hook"] else None
        else:
            old = effective / "pre-commit"
            if (old.is_file() and os.access(old, os.X_OK)
                    and _sha(old.read_bytes()) not in LEGACY_WRAPPER_HASHES):
                previous = str(effective_value / old.name)
            if effective.is_dir():
                for old in effective.iterdir():
                    if old.name != "pre-commit" and old.is_file() and os.access(old, os.X_OK):
                        # Only real Git hook names are dispatched; never overwrite runtime payload.
                        if old.name in FORWARDED_HOOKS:
                            invocation = str(effective_value / old.name)
                            writes[hookdir / old.name] = forwarder_bytes(invocation)
                            forwarded_targets[old.name] = _original_hook(root, hookdir, invocation, old.name)
        owned = set(HOOK_FILES) | {CHAIN_FILE, ACTIVATION_FILE} | owned_forwarders if existing else set()
        for path, content in writes.items():
            if path.parent == hookdir:
                safe(path)
                if path.exists() and path.name not in owned:
                    raise InitError("unowned hook destination collision: " + path.name)
                forwarded[path.name] = _sha(content.encode() if isinstance(content, str) else content)
        retired_hooks = {hookdir / name for name in owned_forwarders - set(forwarded)}
        record = activation_record(root, hookdir, canon, previous, forwarded, forwarded_targets)
        writes[chain] = chain_bytes(record["previous_hook"])
        writes[hookdir / ACTIVATION_FILE] = json.dumps(record, sort_keys=True) + "\n"
        for name in HOOK_FILES:
            writes[hookdir / name] = (canon / "bin" / name).read_bytes()
        exclude = gitpath("--git-path", "info/exclude")
        safe(exclude)
        content = exclude.read_text() if exclude.exists() else ""
        for local_marker in (".agent/.strict-mode", ".agent/.strict-version"):
            if local_marker not in content.splitlines():
                content += ("\n" if content and not content.endswith("\n") else "") + local_marker + "\n"
        writes[exclude] = content
        config_paths = list(dict.fromkeys([common / "config", common / "config.worktree", gitdir / "config.worktree"]))
    safe(root / ".agent/evidence/.preflight")
    for path in list(writes) + config_paths + sorted(retired_hooks):
        safe(path)
    transaction = Transaction()
    try:
        transaction.mkdir(root / ".agent/evidence")
        for path in config_paths:
            transaction.remember(path)
        for path in sorted(retired_hooks):
            transaction.remove(path)
        for path, content in writes.items():
            mode = (0o600 if path.name in {CHAIN_FILE, ACTIVATION_FILE} else 0o755) if hookdir and path.parent == hookdir else None
            transaction.write(path, content, mode)
        if is_git:
            # Enabling worktreeConfig changes how Git reads these two settings: move
            # common values to the main worktree before activating the extension.
            if git(root, "config", "--local", "--get", "extensions.worktreeConfig", check=False) != "true":
                for key in ("core.bare", "core.worktree"):
                    value = git(root, "config", "--file", str(common / "config"), "--get", key, check=False)
                    if value is not None:
                        git(root, "config", "--file", str(common / "config.worktree"), key, value)
                        git(root, "config", "--file", str(common / "config"), "--unset-all", key)
                git(root, "config", "--file", str(common / "config"), "extensions.worktreeConfig", "true")
            git(root, "config", "--worktree", "core.hooksPath", str(hookdir))
            actual = Path(git(root, "rev-parse", "--git-path", "hooks/pre-commit"))
            actual = actual if actual.is_absolute() else root / actual
            if actual != hookdir / "pre-commit" or fail_probe:
                raise InitError("managed hook probe failed")
            git(root, "hook", "run", "pre-commit", "--", "--caphe-probe")
            read_activation(root, hookdir, canon=canon)
            for name in HOOK_FILES:
                if (hookdir / name).read_bytes() != (canon / "bin" / name).read_bytes():
                    raise InitError("effective hook differs from runtime")
        transaction.write(marker, "3\n")
    except BaseException:
        transaction.rollback()
        raise
    print("done. STRICT MODE active. Pre-commit gives FAST GREEN; completion requires --mode completion.")


def main():
    try:
        initialize(os.environ.get("STRICT_MODE_CANON", str(Path.home() / "strict-mode")), Path.cwd())
    except (InitError, OSError, ValueError) as error:
        print("strict-mode init: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
