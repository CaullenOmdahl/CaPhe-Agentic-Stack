#!/usr/bin/env python3
"""Transactional Strict Mode initialization, including worktree-aware hook activation."""
import importlib.util
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


class InitError(RuntimeError):
    pass


# This entry point is also distributed alone as ~/strict-mode.
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


def git(root, *args, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, env=_git_env())
    if check and result.returncode:
        raise InitError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip() if result.returncode == 0 else None


def safe(path):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise InitError("unsafe destination symlink: " + str(component))
    if path.exists() and not path.is_file():
        raise InitError("destination must be a regular file: " + str(path))
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise InitError("destination parent must be a directory")


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
    top = git(root, "rev-parse", "--show-toplevel", check=False)
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
        text = path.read_text() if path.exists() else ""
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
        chain = hookdir / ".caphe-chain.sh"
        if effective.resolve() == hookdir:
            # On refresh preserve the original chain, including an absent original hook.
            if chain.is_file():
                writes[chain] = chain.read_text()
        else:
            old = effective / "pre-commit"
            if old.is_file() and os.access(old, os.X_OK) and not any(line in old.read_text(errors="replace").splitlines() for line in ("# STRICT-MODE:MANAGED-HOOK v2", "# STRICT-MODE:MANAGED-HOOK v3")):
                previous = str(effective_value / old.name)
            writes[chain] = "CAPHE_PREVIOUS_HOOK=" + shlex.quote(previous or "") + "\n"
            if effective.is_dir():
                for old in effective.iterdir():
                    if old.name != "pre-commit" and old.is_file() and os.access(old, os.X_OK):
                        # Only real Git hook names are dispatched; never overwrite runtime payload.
                        if old.name in {"applypatch-msg", "pre-applypatch", "post-applypatch", "pre-merge-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push", "pre-receive", "update", "proc-receive", "post-receive", "post-update", "reference-transaction", "push-to-checkout", "pre-auto-gc", "post-rewrite", "sendemail-validate", "fsmonitor-watchman", "p4-changelist", "p4-prepare-changelist", "p4-post-changelist", "p4-pre-submit", "post-index-change"}:
                            writes[hookdir / old.name] = "#!/usr/bin/env bash\n" + shlex.quote(str(effective_value / old.name)) + ' "$@"\n'
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
    for path in list(writes) + config_paths:
        safe(path)
    transaction = Transaction()
    try:
        transaction.mkdir(root / ".agent/evidence")
        for path in config_paths:
            transaction.remember(path)
        for path, content in writes.items():
            mode = 0o755 if hookdir and path.parent == hookdir and path.name != ".caphe-chain.sh" else None
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
