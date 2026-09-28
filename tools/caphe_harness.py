"""Deterministic, explicit-route CLI worker launcher and environment doctor."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import tempfile
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import io
import uuid
import time
import tomllib
from datetime import datetime, timezone


class HarnessError(ValueError):
    pass


EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
CLIENTS = {"codex", "claude", "agy", "gemini", "glm"}
ROUTE_FIELDS = {"category", "client", "model", "effort", "context_budget_tokens", "permissions",
                "timeout_seconds", "max_output_bytes", "billing", "enabled"}
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "strict-mode" / "templates" / "harness.toml"
WORKER_PROMPT = ROOT / "strict-mode" / "templates" / "worker-prompt.md"
UPDATE_REPOSITORY = "https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack.git"
RELEASES_API = "https://api.github.com/repos/CaullenOmdahl/CaPhe-Agentic-Stack/releases/latest"
RELEASES_BY_TAG_API = "https://api.github.com/repos/CaullenOmdahl/CaPhe-Agentic-Stack/releases/tags/"
KEY_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
             "ZAI_API_KEY", "GLM_API_KEY")


def _closed(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise HarnessError("configuration has missing or unknown fields")


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def validate_config(config):
    _closed(config, {"schema_version", "max_workers", "output_root", "routes"})
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise HarnessError("unsupported harness configuration version")
    if type(config["max_workers"]) is not int or not 1 <= config["max_workers"] <= 16:
        raise HarnessError("max_workers must be between 1 and 16")
    if not isinstance(config["output_root"], str) or not config["output_root"]:
        raise HarnessError("output_root must be a path")
    if not isinstance(config["routes"], list) or not config["routes"]:
        raise HarnessError("routes must be a nonempty list")
    seen = set()
    for route in config["routes"]:
        _closed(route, ROUTE_FIELDS)
        category = route["category"]
        if not isinstance(category, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", category) or category in seen:
            raise HarnessError("route categories must be unique lowercase identifiers")
        seen.add(category)
        if route["client"] not in CLIENTS or not isinstance(route["model"], str) or not route["model"].strip():
            raise HarnessError("route client/model is invalid")
        if route["effort"] not in EFFORTS:
            raise HarnessError("unsupported route effort")
        if type(route["context_budget_tokens"]) is not int or not 1 <= route["context_budget_tokens"] <= 2_000_000:
            raise HarnessError("context_budget_tokens is outside supported bounds")
        if route["permissions"] not in {"read-only", "worktree-write"}:
            raise HarnessError("permissions must be read-only or worktree-write")
        if type(route["timeout_seconds"]) is not int or not 5 <= route["timeout_seconds"] <= 7200:
            raise HarnessError("timeout_seconds must be between 5 and 7200")
        if type(route["max_output_bytes"]) is not int or not 256 <= route["max_output_bytes"] <= 1_000_000:
            raise HarnessError("max_output_bytes is outside supported bounds")
        if route["billing"] not in {"chatgpt", "provider-account", "local"}:
            raise HarnessError("unknown billing mode")
        if type(route["enabled"]) is not bool:
            raise HarnessError("enabled must be boolean")
        if route["client"] == "codex" and route["billing"] != "chatgpt":
            raise HarnessError("Codex ChatGPT routes must use the ChatGPT account mode")
        if route["client"] != "codex" and route["billing"] == "chatgpt":
            raise HarnessError("third-party clients cannot be billed to the ChatGPT plan")
    return config


def load_config(path):
    path = Path(path).expanduser()
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise HarnessError("cannot read harness config") from error
    return validate_config(config), path


def default_config_path():
    override = os.environ.get("CAPHE_HARNESS_CONFIG")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    return base / "caphe" / "harness.toml"


def estimate_tokens(text):
    # No tokenizer is shared across configured providers. This deliberately
    # conservative UTF-8 bound is checked before launch; client usage is recorded after.
    return max(1, (len(text.encode("utf-8")) + 2) // 3)


def _extract_validated_tar(bundle, target, label):
    members = bundle.getmembers()
    for member in members:
        name = PurePosixPath(member.name)
        if (member.issym() or member.islnk() or member.isdev() or name.is_absolute()
                or ".." in name.parts or member.mode & 0o7000
                or not (member.isfile() or member.isdir())):
            raise HarnessError(label + " archive contains unsafe entries")
    kwargs = {"members": members}
    if callable(getattr(tarfile.TarFile, "data_filter", None)):
        kwargs["filter"] = "data"
    bundle.extractall(target, **kwargs)


def build_command(route, prompt_path, output_path, repo, config_profile="caphe-worker"):
    """Build explicit argv using a per-run permission profile, never a broad sandbox mode."""
    if route["client"] != "codex":
        raise HarnessError("client adapter is not enabled until route evidence and isolation are implemented")
    args = ["codex", "exec", "--json", "--ignore-user-config", "--profile", config_profile,
            "--model", route["model"],
            "--config", 'model_reasoning_effort="' + route["effort"] + '"',
            "--config", "agents.max_depth=0", "--output-last-message", str(output_path), "--cd", str(repo)]
    args.append("-")
    return args


def _snapshot_repo(repo, target, revision=None):
    """Build a standalone tracked-only Git snapshot; no parent conversation or dirty files."""
    repo, target = Path(repo).resolve(), Path(target)
    if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[a-fA-F0-9]{40,64}", revision)):
        raise HarnessError("source snapshot revision must be a verified Git object ID")
    revision = revision or "HEAD"
    tree = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", revision], capture_output=True,
                         timeout=20, env=_child_env("codex"))
    if tree.returncode or any(line.startswith(b"160000 commit ") for line in tree.stdout.splitlines()):
        raise HarnessError("source snapshot failed or contains submodules that need explicit handling")
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", revision],
                             capture_output=True, timeout=60, env=_child_env("codex"))
    if archive.returncode or len(archive.stdout) > 512 * 1024 * 1024:
        raise HarnessError("tracked source snapshot failed or exceeds the 512 MiB limit")
    target.mkdir(mode=0o700)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            _extract_validated_tar(bundle, target, "source snapshot")
    except (tarfile.TarError, OSError) as error:
        raise HarnessError("tracked source snapshot could not be safely unpacked") from error
    git_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_AUTHOR_NAME": "CaPhe Harness", "GIT_AUTHOR_EMAIL": "harness@localhost",
               "GIT_COMMITTER_NAME": "CaPhe Harness", "GIT_COMMITTER_EMAIL": "harness@localhost"}
    for args in (["init", "--quiet", str(target)], ["-C", str(target), "add", "--force", "--all"],
                 ["-C", str(target), "-c", "core.hooksPath=/dev/null", "commit", "--quiet", "-m", "harness source snapshot"]):
        result = subprocess.run(["git", *args], capture_output=True, env=git_env, timeout=30)
        if result.returncode:
            raise HarnessError("standalone source snapshot could not be initialized")
    return target


def _write_codex_profile(home, route, allowed_writes=(), config_profile="caphe-worker", output_path=None):
    scoped = ['"." = "read"']
    if route["permissions"] == "worktree-write":
        scoped.extend(json.dumps(path) + ' = "write"' for path in allowed_writes)
    codex_home = Path(home).resolve()
    filesystem = ('{ ":minimal" = "read", ":workspace_roots" = { ' + ", ".join(scoped) + " }, "
                  + json.dumps(str(codex_home / "auth.json")) + ' = "deny", '
                  + json.dumps(str(codex_home / "sessions" / "**")) + ' = "deny"')
    if output_path is not None:
        output_path = Path(output_path).expanduser().resolve(strict=False)
        filesystem += ", " + json.dumps(str(output_path)) + ' = "write"'
    filesystem += " }"
    profile = codex_home / (config_profile + ".config.toml")
    profile.write_text(
        'model_reasoning_effort = "' + route["effort"] + '"\n'
        'default_permissions = "caphe-worker"\n'
        '[permissions.caphe-worker]\n'
        'filesystem = ' + filesystem + '\n'
        'network = { enabled = false }\n', encoding="utf-8")
    profile.chmod(0o600)
    return profile


def _prepare_codex_profile(route, allowed_writes=(), config_profile="caphe-worker", output_path=None):
    home = Path(_child_env("codex")["CODEX_HOME"]).expanduser()
    if home.is_symlink() or not home.is_dir() or home.stat().st_uid != os.getuid():
        raise HarnessError("Codex home must be an existing directory owned by the current user")
    profile = home / (config_profile + ".config.toml")
    if profile.exists() or profile.is_symlink():
        raise HarnessError("temporary Codex profile name is already in use")
    _write_codex_profile(home, route, allowed_writes, config_profile, output_path)
    return home, profile


def _codex_profile_parse_check(route):
    executable = shutil.which("codex")
    if not executable:
        return {"supported": False, "reason": "Codex CLI is not installed"}
    # Keep the worker workspace outside TMPDIR. macOS gives processes broad
    # access to their selected temporary root, which would invalidate a test
    # when /private/tmp also contains the workspace under test.
    with tempfile.TemporaryDirectory(prefix="caphe-profile-check-", dir=str(Path.home())) as home_tmp:
        try:
            home_root = Path(home_tmp).resolve()
            home = str(home_root / "codex-home")
            Path(home).mkdir(mode=0o700)
            workspace = home_root / "workspace"
            workspace.mkdir(mode=0o700)
            sandbox_tmp = home_root / "codex-tmp"
            sandbox_tmp.mkdir(mode=0o700)
            output_path = home_root / "worker-result.txt"
            (workspace / "allowed.txt").write_text("before", encoding="utf-8")
            (workspace / "blocked.txt").write_text("before", encoding="utf-8")
            (Path(home) / "auth.json").write_text("CAPHE_SECRET_SENTINEL", encoding="utf-8")
            sessions = Path(home) / "sessions"
            sessions.mkdir(mode=0o700)
            (sessions / "parent.jsonl").write_text("CAPHE_PARENT_SENTINEL", encoding="utf-8")
            profile_name = "caphe-doctor-check"
            allowed = ("allowed.txt",) if route["permissions"] == "worktree-write" else ()
            _write_codex_profile(home, route, allowed, profile_name, output_path)
            env = {**_child_env("codex"), "CODEX_HOME": home, "TMPDIR": str(sandbox_tmp)}
            parse = subprocess.run([executable, "--profile", profile_name, "debug", "prompt-input", "profile check"],
                                   env=env, capture_output=True, timeout=15)
            if parse.returncode:
                return {"supported": False, "reason": "restricted profile could not be parsed"}
            def sandbox(*command):
                return subprocess.run([executable, "sandbox", "--profile", profile_name,
                                       "--permission-profile", "caphe-worker", "--cd", str(workspace),
                                       *command], env=env, capture_output=True, timeout=15)
            for protected in (Path(home) / "auth.json", sessions / "parent.jsonl"):
                denied = sandbox("cat", str(protected))
                if denied.returncode == 0 or b"CAPHE_" in denied.stdout:
                    return {"supported": False, "reason": "filesystem profile can read protected Codex data"}
            blocked_write = sandbox("sh", "-c", "printf after > blocked.txt")
            if blocked_write.returncode == 0 or (workspace / "blocked.txt").read_text() != "before":
                return {"supported": False, "reason": "filesystem profile allows an undeclared write"}
            if route["permissions"] == "worktree-write":
                allowed_write = sandbox("sh", "-c", "printf after > allowed.txt")
                if allowed_write.returncode or (workspace / "allowed.txt").read_text() != "after":
                    return {"supported": False, "reason": "filesystem profile blocks a declared write"}
            result_write = sandbox("sh", "-c", "printf after > " + shlex.quote(str(output_path)))
            if result_write.returncode or output_path.read_text() != "after":
                return {"supported": False, "reason": "filesystem profile blocks its designated result file"}
            return {"supported": True, "reason": None, "filesystem_enforced": True}
        except (OSError, subprocess.SubprocessError):
            return {"supported": False, "reason": "restricted filesystem profile could not be enforced"}


def _allowed_write_paths(paths):
    normalized = []
    for value in paths:
        if not isinstance(value, str) or not value or "\\" in value or ":" in value:
            raise HarnessError("allowed write paths must be repository-relative paths")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
            raise HarnessError("allowed write path is not normalized")
        if ".git" in path.parts:
            raise HarnessError("Git metadata cannot be declared writable")
        normalized.append(value.rstrip("/"))
    if len(normalized) != len(set(normalized)):
        raise HarnessError("allowed write paths must be unique")
    return normalized


def _validate_run_reference(value, field):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value)):
        raise HarnessError(field + " must be a bounded run id")
    return value


def _tree_manifest(root, *, max_bytes=512 * 1024 * 1024, max_entries=250_000, timeout_seconds=30):
    root = Path(root).resolve(strict=True)
    manifest = {}
    pending = [root]
    total_bytes = 0
    deadline = time.monotonic() + timeout_seconds
    while pending:
        if time.monotonic() > deadline:
            return None
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            return None
        for entry in entries:
            if time.monotonic() > deadline:
                return None
            if directory == root and entry.name == ".git":
                continue
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    manifest[relative] = ("directory", mode, None)
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    total_bytes += info.st_size
                    if total_bytes > max_bytes:
                        return None
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                            if time.monotonic() > deadline:
                                return None
                    manifest[relative] = ("file", mode, digest.hexdigest())
                elif stat.S_ISLNK(info.st_mode):
                    target = os.readlink(path).encode("utf-8", "surrogateescape")
                    manifest[relative] = ("symlink", mode, hashlib.sha256(target).hexdigest())
                else:
                    return None
            except OSError:
                return None
            if len(manifest) > max_entries:
                return None
    return manifest


def _worktree_changes(root, baseline=None):
    root = Path(root).resolve()
    if baseline is not None:
        current = _tree_manifest(root)
        if current is None:
            return None
        return sorted(path for path in set(baseline) | set(current) if baseline.get(path) != current.get(path))
    try:
        proc = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--no-renames", "-z", "HEAD"],
                              capture_output=True, timeout=20, env=_child_env("codex"))
        # Include both ignored and ordinary untracked files at file granularity;
        # directory roll-ups cannot be compared to a declared individual output.
        untracked = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "-z"],
                                   capture_output=True, timeout=20, env=_child_env("codex"))
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode or untracked.returncode:
        return None
    return sorted(set(part.decode("utf-8", "surrogateescape") for part in proc.stdout.split(b"\0") if part)
                  | set(part.decode("utf-8", "surrogateescape") for part in untracked.stdout.split(b"\0") if part))


def _changes_allowed(paths, allowed):
    return all(any(path == prefix or path.startswith(prefix + "/") for prefix in allowed) for path in paths)


def _effective_route_verified(route, effective, workspace):
    if not isinstance(effective, dict) or effective.get("model") != route["model"] or effective.get("effort") != route["effort"]:
        return False
    profile = effective.get("permission_profile")
    sandbox = effective.get("sandbox_policy")
    cwd = effective.get("cwd")
    if not isinstance(profile, dict) or (profile.get("name") or profile.get("profile")) != "caphe-worker":
        return False
    if not isinstance(sandbox, dict) or sandbox.get("type") == "danger-full-access":
        return False
    if not isinstance(cwd, str):
        return False
    try:
        return Path(cwd).resolve(strict=True) == Path(workspace).resolve(strict=True)
    except (OSError, RuntimeError):
        return False


def _bounded_result(path, max_bytes):
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "r+b") as result_stream:
        info = os.fstat(result_stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("result is not a regular file")
        data = result_stream.read(max_bytes)
        truncated = info.st_size > max_bytes
        if truncated:
            result_stream.seek(0)
            result_stream.write(data)
            result_stream.truncate(max_bytes)
        if hasattr(os, "fchmod"):
            os.fchmod(result_stream.fileno(), 0o600)
    return data, truncated


def _child_env(client):
    keep = {"PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
            "COLORTERM", "NO_COLOR", "SSL_CERT_FILE", "SSL_CERT_DIR", "SYSTEMROOT", "WINDIR"}
    result = {key: value for key, value in os.environ.items() if key in keep}
    # Route authentication comes from the selected CLI's account store, never API-key
    # environment variables inherited from the coordinator.
    result["PATH"] = result.get("PATH", "/usr/bin:/bin")
    if client == "codex":
        result["CODEX_HOME"] = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    return result


def _safe_output_dir(path, repo):
    root_probe = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, timeout=20, env=_child_env("codex"))
    if root_probe.returncode or not root_probe.stdout.strip():
        raise HarnessError("source repository root could not be verified")
    repo = Path(root_probe.stdout.strip()).resolve()
    candidate = Path(path).expanduser().absolute()
    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise HarnessError("run output path cannot contain symlinks")
    root = candidate.resolve(strict=False)
    if root == repo or root.is_relative_to(repo) or repo.is_relative_to(root):
        raise HarnessError("run output must be separate from the source repository")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid():
        raise HarnessError("run output directory is not owned by the current user")
    root.chmod(0o700)
    return root


def _git_clean(repo):
    result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=normal"],
                            capture_output=True, text=True, timeout=20,
                            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
                                 "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
    if result.returncode:
        raise HarnessError("source repository state could not be verified")
    if result.stdout.strip():
        raise HarnessError("CLI workers require a clean source checkout")


def _json_records(text):
    records = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _context_payload(record):
    for key in ("payload", "context", "data"):
        value = record.get(key)
        if isinstance(value, dict):
            return value
    return record


def codex_effective_route(thread_id, sessions_root):
    if not isinstance(thread_id, str) or not re.fullmatch(r"[A-Fa-f0-9-]{20,64}", thread_id):
        return None
    candidates = list(Path(sessions_root).glob(f"**/rollout-*-{thread_id}.jsonl"))
    if len(candidates) != 1 or candidates[0].is_symlink():
        return None
    found = None
    try:
        with candidates[0].open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "turn_context":
                    continue
                payload = _context_payload(record)
                effort = payload.get("effort") or payload.get("reasoning_effort")
                mode = payload.get("collaboration_mode")
                if not effort and isinstance(mode, dict):
                    settings = mode.get("settings")
                    if isinstance(settings, dict):
                        effort = settings.get("reasoning_effort")
                model = payload.get("model")
                if isinstance(model, str) and isinstance(effort, str):
                    found = {"model": model, "effort": effort,
                             "cwd": payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
                             "permission_profile": payload.get("permission_profile"),
                             "sandbox_policy": payload.get("sandbox_policy")}
                    break
    except OSError:
        return None
    return found


def _usage_object(value):
    if isinstance(value, dict):
        aliases = {"input_tokens": ("input_tokens", "total_input_tokens"),
                   "cached_input_tokens": ("cached_input_tokens", "cache_read_input_tokens"),
                   "output_tokens": ("output_tokens", "total_output_tokens"),
                   "reasoning_tokens": ("reasoning_tokens", "reasoning_output_tokens")}
        usage = {}
        for target, keys in aliases.items():
            for key in keys:
                candidate = value.get(key)
                if type(candidate) is int and candidate >= 0:
                    usage[target] = candidate
                    break
        if "input_tokens" in usage and "output_tokens" in usage:
            usage["output_includes_reasoning"] = None
            return usage
        for nested in value.values():
            found = _usage_object(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in reversed(value):
            found = _usage_object(nested)
            if found:
                return found
    return None


def codex_session_evidence(thread_id, sessions_root):
    if not isinstance(thread_id, str) or not re.fullmatch(r"[A-Fa-f0-9-]{20,64}", thread_id):
        return None
    candidates = list(Path(sessions_root).glob(f"**/rollout-*-{thread_id}.jsonl"))
    if len(candidates) != 1 or candidates[0].is_symlink():
        return None
    route, usage = None, None
    try:
        with candidates[0].open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") == "turn_context":
                    payload = _context_payload(record)
                    effort = payload.get("effort") or payload.get("reasoning_effort")
                    mode = payload.get("collaboration_mode")
                    if not effort and isinstance(mode, dict):
                        settings = mode.get("settings")
                        if isinstance(settings, dict):
                            effort = settings.get("reasoning_effort")
                    model = payload.get("model")
                    if isinstance(model, str) and isinstance(effort, str):
                        route = {"model": model, "effort": effort,
                                 "cwd": payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
                                 "permission_profile": payload.get("permission_profile"),
                                 "sandbox_policy": payload.get("sandbox_policy")}
                if record.get("type") in {"token_usage_record", "token_count"}:
                    usage = _usage_object(_context_payload(record)) or usage
    except OSError:
        return None
    return {"route": route, "usage": usage} if route or usage else None


def _run_process(argv, *, cwd, env, prompt, timeout):
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=(os.name == "posix"))
    limits = {"stdout": 8 * 1024 * 1024, "stderr": 1024 * 1024}
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}

    def drain(name, stream):
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            available = limits[name] - len(captured[name])
            if available > 0:
                captured[name].extend(chunk[:available])
            if len(chunk) > available:
                truncated[name] = True

    def feed():
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    readers = [threading.Thread(target=drain, args=(name, getattr(proc, name)), daemon=True)
               for name in ("stdout", "stderr")]
    for reader in readers:
        reader.start()
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    try:
        proc.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            proc.wait()
    writer.join(timeout=2)
    for reader in readers:
        reader.join(timeout=5)
    if any(reader.is_alive() for reader in readers):
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    return (124 if timed_out else proc.returncode, bytes(captured["stdout"]), bytes(captured["stderr"]),
            timed_out, truncated["stdout"], truncated["stderr"])


def run_worker(config, route, repo, brief, *, execute=False, allowed_writes=(), parent_run_id=None,
               retry_of=None, batch_id=None):
    parent_run_id = _validate_run_reference(parent_run_id, "parent_run_id")
    retry_of = _validate_run_reference(retry_of, "retry_of")
    batch_id = _validate_run_reference(batch_id, "batch_id")
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise HarnessError("repository path does not exist")
    try:
        prompt = WORKER_PROMPT.read_text(encoding="utf-8") + "\n" + brief
    except OSError as error:
        raise HarnessError("worker prompt template is unavailable") from error
    estimated = estimate_tokens(prompt)
    if estimated > route["context_budget_tokens"]:
        raise HarnessError(f"brief estimate {estimated} exceeds route budget {route['context_budget_tokens']}")
    allowed_writes = _allowed_write_paths(allowed_writes)
    if route["permissions"] == "read-only" and allowed_writes:
        raise HarnessError("read-only routes cannot declare writable paths")
    if route["permissions"] == "worktree-write" and not allowed_writes:
        raise HarnessError("worktree-write routes require explicit --allow-write paths")
    run_root = _safe_output_dir(Path(config["output_root"]).expanduser(), repo)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + os.urandom(6).hex()
    run_dir = run_root / run_id
    run_dir.mkdir(mode=0o700)
    prompt_path, output_path = run_dir / "brief.txt", run_dir / "result.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    prompt_path.chmod(0o600)
    source = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                            timeout=20, env=_child_env("codex"))
    if source.returncode:
        raise HarnessError("source revision could not be verified")
    record = {"schema_version": 1, "run_id": run_id, "category": route["category"],
              "client": route["client"], "requested_model": route["model"], "requested_effort": route["effort"],
              "billing": route["billing"], "permissions": route["permissions"],
              "requested_permission_profile": "caphe-worker" if route["client"] == "codex" else None,
              "context_budget_tokens": route["context_budget_tokens"], "estimated_prompt_tokens": estimated,
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "source_revision": source.stdout.strip(),
              "allowed_writes": allowed_writes, "parent_run_id": parent_run_id, "retry_of": retry_of,
              "batch_id": batch_id,
              "result_path": str(output_path), "status": "planned", "effective_model": None,
              "effective_effort": None, "usage": None, "elapsed_seconds": None}
    if not execute:
        record["status"] = "planned"
        record["execution_blocker"] = "execution requires explicit --execute and a supported isolated Codex profile"
        return record
    profile_path = None
    config_profile = "caphe-worker-" + run_id.lower().replace("z-", "-")
    try:
        _git_clean(repo)
        if route["client"] != "codex":
            raise HarnessError("only the Codex subprocess adapter is currently enabled")
        auth = _command_status("codex")
        if not auth["installed"] or not auth["authenticated"] or auth.get("auth_mode") != "chatgpt":
            raise HarnessError("Codex ChatGPT login is not verified; refusing this billing route")
        workspace = _snapshot_repo(repo, run_dir / "workspace", source.stdout.strip())
        baseline = _tree_manifest(workspace)
        if baseline is None:
            raise HarnessError("immutable source snapshot could not be inventoried")
        sandbox_tmp = run_dir / "codex-tmp"
        sandbox_tmp.mkdir(mode=0o700)
        home, profile_path = _prepare_codex_profile(route, allowed_writes, config_profile, output_path)
        argv = build_command(route, prompt_path, output_path, workspace, config_profile)
    except (HarnessError, OSError, subprocess.SubprocessError, ValueError) as error:
        if profile_path and profile_path.is_file() and not profile_path.is_symlink():
            profile_path.unlink()
        record.update(status="preflight_failed", execution_error=str(error), elapsed_seconds=0)
        record_path = run_dir / "run.json"
        record_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        record_path.chmod(0o600)
        return record
    child_env = _child_env(route["client"])
    child_env["TMPDIR"] = str(sandbox_tmp)
    started = time.monotonic()
    try:
        status, stdout, stderr, timed_out, events_truncated, stderr_truncated = _run_process(
            argv, cwd=workspace, env=child_env, prompt=prompt, timeout=route["timeout_seconds"])
    except OSError as error:
        status, stdout, stderr, timed_out, events_truncated, stderr_truncated = (
            127, b"", str(error).encode("utf-8", "replace"), False, False, False)
    finally:
        if profile_path and profile_path.is_file() and not profile_path.is_symlink():
            profile_path.unlink()
    elapsed = time.monotonic() - started
    out_path = run_dir / "events.jsonl"
    out_path.write_bytes(stdout)
    out_path.chmod(0o600)
    error_path = run_dir / "stderr.txt"
    error_path.write_bytes(stderr)
    error_path.chmod(0o600)
    thread_id = None
    for item in _json_records(stdout.decode("utf-8", "replace")):
        if item.get("type") == "thread.started":
            thread_id = item.get("thread_id") or item.get("threadId")
            break
    evidence = codex_session_evidence(thread_id, home / "sessions") if thread_id else None
    effective = evidence.get("route") if evidence else None
    effective_cwd = effective.get("cwd") if effective else None
    record.update(status="timed_out" if timed_out else "completed" if status == 0 else "failed",
              exit_code=status, elapsed_seconds=round(elapsed, 3), thread_id=thread_id,
                  events_path=str(out_path), effective_model=effective.get("model") if effective else None,
              effective_effort=effective.get("effort") if effective else None,
              effective_permission_profile=effective.get("permission_profile") if effective else None,
              effective_sandbox_policy=effective.get("sandbox_policy") if effective else None,
              route_verified=_effective_route_verified(route, effective, workspace),
                  usage=evidence.get("usage") if evidence else None, stderr_path=str(error_path))
    record["events_truncated"] = events_truncated
    record["stderr_truncated"] = stderr_truncated
    if route["permissions"] == "worktree-write":
        if not isinstance(effective_cwd, str):
            record["write_scope_verified"] = False
        else:
            try:
                work_root = subprocess.run(["git", "-C", effective_cwd, "rev-parse", "--show-toplevel"],
                                           capture_output=True, text=True, timeout=20, env=_child_env("codex"))
            except (OSError, subprocess.SubprocessError):
                work_root = None
            if work_root is None or work_root.returncode or Path(work_root.stdout.strip()).resolve() != workspace:
                record["write_scope_verified"] = False
            else:
                changed = _worktree_changes(work_root.stdout.strip(), baseline)
                record["worktree"] = work_root.stdout.strip()
                record["changed_paths"] = changed
                record["write_scope_verified"] = bool(changed is not None and _changes_allowed(changed, allowed_writes))
        if record["write_scope_verified"] is False and record.get("status") == "completed":
            record["status"] = "rejected_write_scope"
    try:
        if output_path.is_file() and not output_path.is_symlink():
            _, truncated = _bounded_result(output_path, route["max_output_bytes"])
            if truncated:
                record["result_truncated"] = True
        else:
            record["result_path"] = None
    except OSError as error:
        record["result_path"] = None
        record["result_read_error"] = str(error)
    if record.get("result_path") and not output_path.exists():
        record["result_path"] = None
    if record.get("route_verified") is not True and record.get("status") == "completed":
        record["status"] = "unverified"
    record_path = run_dir / "run.json"
    record_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    record_path.chmod(0o600)
    return record


def run_batch(config, tasks, *, execute=False, parent_run_id=None):
    parent_run_id = _validate_run_reference(parent_run_id, "parent_run_id")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 64:
        raise HarnessError("batch must contain between 1 and 64 worker tasks")
    routes = {route["category"]: route for route in config["routes"]}
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + os.urandom(6).hex()
    prepared = []
    for task in tasks:
        _closed(task, {"category", "repo", "brief_file"}, {"allow_write", "retry_of"})
        route = routes.get(task["category"])
        if not route or not route["enabled"]:
            raise HarnessError("batch references a missing or disabled route")
        if not isinstance(task["repo"], str) or not isinstance(task["brief_file"], str):
            raise HarnessError("batch repo and brief_file must be paths")
        writes = task.get("allow_write", [])
        if not isinstance(writes, list):
            raise HarnessError("batch allow_write must be a list")
        writes = _allowed_write_paths(writes)
        if route["permissions"] == "read-only" and writes:
            raise HarnessError("read-only routes cannot declare writable paths")
        if route["permissions"] == "worktree-write" and not writes:
            raise HarnessError("worktree-write routes require explicit allow_write paths")
        brief_path = Path(task["brief_file"]).expanduser()
        if brief_path.is_symlink() or not brief_path.is_file():
            raise HarnessError("batch briefs must be regular files")
        if brief_path.stat().st_size > route["context_budget_tokens"] * 3:
            raise HarnessError("batch brief exceeds the route context budget")
        brief = brief_path.read_text(encoding="utf-8")
        retry_of = _validate_run_reference(task.get("retry_of"), "retry_of")
        prepared.append((route, task["repo"], brief, writes, retry_of))

    outcomes = [None] * len(prepared)
    with ThreadPoolExecutor(max_workers=config["max_workers"], thread_name_prefix="caphe-worker") as pool:
        future_map = {pool.submit(run_worker, config, route, repo, brief, execute=execute,
                                  allowed_writes=writes, parent_run_id=parent_run_id or batch_id,
                                  retry_of=retry_of, batch_id=batch_id): index
                      for index, (route, repo, brief, writes, retry_of) in enumerate(prepared)}
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                outcomes[index] = future.result()
            except (HarnessError, OSError, subprocess.SubprocessError, ValueError) as error:
                outcomes[index] = {"status": "error", "category": prepared[index][0]["category"],
                                   "reason": str(error)}
    return {"status": "completed" if all(item.get("status") in {"planned", "completed"} for item in outcomes)
            else "partial_or_failed", "batch_id": batch_id, "max_workers": config["max_workers"],
            "tasks": outcomes}


def _command_status(binary, args=(), timeout=8):
    executable = shutil.which(binary)
    if not executable:
        return {"installed": False, "version": None, "authenticated": False}
    version_run = subprocess.run([executable, "--version"], text=True, capture_output=True, timeout=timeout)
    version = (version_run.stdout or version_run.stderr).strip().splitlines()
    authenticated = False
    mode = None
    if binary == "codex":
        auth_run = subprocess.run([executable, "login", "status"], text=True, capture_output=True, timeout=timeout)
        message = (auth_run.stdout + " " + auth_run.stderr).lower()
        authenticated = auth_run.returncode == 0 and "logged in" in message
        mode = "chatgpt" if "chatgpt" in message else "api_key" if "api key" in message else "unknown"
    elif binary == "claude":
        auth_run = subprocess.run([executable, "auth", "status", "--json"], text=True, capture_output=True, timeout=timeout)
        try:
            data = json.loads(auth_run.stdout)
            authenticated = bool(data.get("loggedIn") or data.get("authenticated"))
            mode = data.get("authMethod") if isinstance(data.get("authMethod"), str) else "unknown"
        except (json.JSONDecodeError, AttributeError):
            pass
    elif binary == "agy":
        # agy has no stable, non-interactive auth-status contract in the installed CLI.
        pass
    return {"installed": version_run.returncode == 0, "version": version[0] if version else None,
            "authenticated": authenticated, "auth_mode": mode}


def doctor(config_path, *, apply=False, probe=False):
    path = Path(config_path).expanduser()
    created = False
    if not path.exists() and apply:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.stat().st_uid != os.getuid():
            raise HarnessError("configuration directory is not owned by the current user")
        path.parent.chmod(0o700)
        data = TEMPLATE.read_bytes()
        fd, temporary = tempfile.mkstemp(prefix=".harness-config-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        created = True
    if not path.is_file() or path.is_symlink():
        raise HarnessError("harness config is missing; run `harness doctor --apply` to create the reviewed template")
    config, _ = load_config(path)
    client_names = sorted({"codex", "claude", *{route["client"] for route in config["routes"]}})
    clients = {name: _command_status(name) for name in client_names}
    ccusage = _command_status("ccusage")
    profiles = {route["category"]: (_codex_profile_parse_check(route) if route["client"] == "codex"
                                    else {"supported": False, "reason": "client adapter is not enabled"})
                for route in config["routes"]}
    env_keys = sorted(name for name in KEY_NAMES if name in os.environ)
    enabled = []
    for route in config["routes"]:
        installed = clients[route["client"]]["installed"]
        authenticated = clients[route["client"]]["authenticated"]
        effective_evidence_supported = False  # no verified restricted filesystem profile yet
        billing_ok = (route["client"] == "codex" and route["billing"] == "chatgpt"
                      and clients[route["client"]].get("auth_mode") == "chatgpt")
        enabled.append({"category": route["category"], "enabled": route["enabled"],
                        "ready": bool(route["enabled"] and installed and authenticated
                                      and effective_evidence_supported and billing_ok),
                        "reason": None if route["enabled"] and installed and authenticated
                        and effective_evidence_supported and billing_ok else
                        "disabled or needs an explicit live probe of effective route, account, and permissions"})
    output = Path(config["output_root"]).expanduser()
    report = {"config_path": str(path), "config_created": created,
              "clients": clients, "environment_key_names_present": env_keys,
              "routes": enabled, "codex_profiles": profiles,
              "ccusage": {"installed": ccusage["installed"], "version": ccusage["version"]},
              "native_spawn": "unused; workers are separate CLI processes",
              "machine_codex_config": "unchanged; model and effort are passed per invocation",
              "output_root": {"path": str(output), "exists": output.exists(),
                              "private": bool(output.exists() and stat.S_IMODE(output.stat().st_mode) & 0o077 == 0)},
              "update_trust": {"fingerprint_configured": bool(os.environ.get("CAPHE_RELEASE_SIGNING_FINGERPRINT")),
                               "keyring_configured": bool(os.environ.get("CAPHE_UPDATE_GNUPGHOME"))}}
    if probe:
        report["probes"] = []
        with tempfile.TemporaryDirectory(prefix="caphe-route-probe-") as tmp:
            probe_repo = Path(tmp) / "repo"
            probe_repo.mkdir()
            subprocess.run(["git", "init", "--quiet", str(probe_repo)], check=True, timeout=10)
            subprocess.run(["git", "-C", str(probe_repo), "-c", "user.name=Caphe Probe",
                            "-c", "user.email=probe@example.invalid", "commit", "--allow-empty", "-qm", "probe"],
                           check=True, timeout=10)
            for route in config["routes"]:
                if route["enabled"] and route["client"] != "codex":
                    report["probes"].append({"category": route["category"], "status": "unsupported",
                                             "reason": "only the Codex adapter is implemented"})
                elif route["enabled"] and clients[route["client"]]["installed"]:
                    outcome = run_worker(config, route, probe_repo,
                                         "This is a route verification probe. Reply with exactly the supplied marker and do not use tools. Marker: "
                                         + "CAPHE_PROBE_" + os.urandom(6).hex(), execute=True,
                                         allowed_writes=("CAPHE_PROBE_MARKER.txt",)
                                         if route["permissions"] == "worktree-write" else ())
                    report["probes"].append({"category": route["category"], "status": outcome["status"],
                                             "route_verified": outcome.get("route_verified", False),
                                             "effective_model": outcome.get("effective_model"),
                                             "effective_effort": outcome.get("effective_effort"),
                                             "usage": outcome.get("usage")})
        probed = {item["category"]: item for item in report["probes"]}
        for item in report["routes"]:
            result = probed.get(item["category"])
            if result is not None:
                item["ready"] = result.get("route_verified") is True and result.get("status") == "completed"
                item["reason"] = None if item["ready"] else "live route probe did not verify the requested route"
    return report


def _parse_release(raw):
    if len(raw) > 256 * 1024:
        raise HarnessError("release metadata exceeds size limit")
    try:
        release = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HarnessError("GitHub returned invalid release metadata") from error
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if (not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", tag)
            or release.get("draft") is not False or release.get("prerelease") is not False):
        raise HarnessError("release is not a stable, versioned release")
    return {"tag": tag, "name": str(release.get("name") or tag),
            "published_at": release.get("published_at"), "html_url": release.get("html_url")}


def _release_from_url(url):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                    "User-Agent": "caphe-harness/1"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(256 * 1024 + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise HarnessError("no published GitHub release exists") from error
        raise HarnessError("GitHub release lookup failed") from error
    except (OSError, urllib.error.URLError) as error:
        raise HarnessError("GitHub release lookup failed") from error
    return _parse_release(raw)


def latest_release():
    return _release_from_url(RELEASES_API)


def release_by_tag(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", tag):
        raise HarnessError("an exact stable version tag is required")
    release = _release_from_url(RELEASES_BY_TAG_API + urllib.parse.quote(tag, safe=""))
    if release["tag"] != tag:
        raise HarnessError("GitHub returned a different release tag")
    return release


def _git(args, *, cwd, env, timeout=90, binary=False):
    try:
        result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise HarnessError("Git update operation failed") from error
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace")[-2000:]
        raise HarnessError("Git update operation failed: " + message)
    return result.stdout if binary else result.stdout.decode("utf-8", "replace").strip()


def _release_trust():
    fingerprint = os.environ.get("CAPHE_RELEASE_SIGNING_FINGERPRINT", "").replace(" ", "").upper()
    gnupg = os.environ.get("CAPHE_UPDATE_GNUPGHOME")
    if not re.fullmatch(r"[A-F0-9]{40,64}", fingerprint) or not gnupg:
        raise HarnessError("signed updates are disabled; configure an independent release fingerprint and GPG keyring")
    keyring = Path(gnupg).expanduser()
    if keyring.is_symlink() or not keyring.is_dir() or keyring.stat().st_uid != os.getuid():
        raise HarnessError("release keyring must be an existing directory owned by the current user")
    return fingerprint, keyring


def _verify_tag(tag, repo_dir, fingerprint, keyring):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
           "GNUPGHOME": str(keyring), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    tag_object = _git(["cat-file", "-t", "refs/tags/" + tag], cwd=repo_dir, env=env)
    if tag_object != "tag":
        raise HarnessError("release must use an annotated signed tag")
    proc = subprocess.run(["git", "verify-tag", "--raw", tag], cwd=repo_dir, env=env,
                          capture_output=True, timeout=30)
    status = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    fingerprints = re.findall(r"\[GNUPG:\] VALIDSIG ([A-Fa-f0-9]{40,64})", status)
    if proc.returncode or not fingerprints or fingerprints[0].upper() != fingerprint:
        raise HarnessError("release tag signature is invalid or signed by an untrusted key")
    return env


def _stage_release(tag, fingerprint, keyring, base):
    git_dir = base / "release.git"
    git_dir.mkdir(mode=0o700)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    _git(["init", "--bare", str(git_dir)], cwd=base, env=env)
    _git(["--git-dir", str(git_dir), "remote", "add", "origin", UPDATE_REPOSITORY], cwd=base, env=env)
    _git(["--git-dir", str(git_dir), "fetch", "--depth=1", "--no-tags", "origin",
          f"refs/tags/{tag}:refs/tags/{tag}"], cwd=base, env=env, timeout=180)
    env = _verify_tag(tag, git_dir, fingerprint, keyring)
    archive = _git(["--git-dir", str(git_dir), "archive", "--format=tar", tag], cwd=base, env=env, binary=True)
    if len(archive) > 128 * 1024 * 1024:
        raise HarnessError("release source exceeds size limit")
    source = base / "source"
    source.mkdir(mode=0o700)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            _extract_validated_tar(bundle, source, "release")
    except (tarfile.TarError, OSError) as error:
        raise HarnessError("release archive could not be safely unpacked") from error
    _git(["init", "--quiet", str(source)], cwd=base, env=env)
    _stage_release_files(source, base, env)
    return source, hashlib.sha256(archive).hexdigest(), env


def _stage_release_files(source, base, env):
    _git(["-C", str(source), "-c", "core.hooksPath=/dev/null", "add", "--force", "--all"], cwd=base, env=env)


def _load_staged_installer(stage):
    path = Path(stage) / "tools" / "stack_install.py"
    if path.is_symlink() or not path.is_file():
        raise HarnessError("signed release does not contain a regular stack installer")
    spec = importlib.util.spec_from_file_location("caphe_staged_stack_install", path)
    if spec is None or spec.loader is None:
        raise HarnessError("signed release stack installer could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = ("plan_runtime_install", "_entries_digest", "apply_runtime_plan")
    if any(not callable(getattr(module, name, None)) for name in required):
        raise HarnessError("signed release stack installer has an unsupported interface")
    return module


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _write_update_preview(state, report):
    payload = {"schema_version": 1, "report": report}
    encoded = _canonical_json(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    directory = state / "previews"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise HarnessError("update preview store is not a private owned directory")
    directory.chmod(0o700)
    path = directory / (digest + ".json")
    contents = encoded + b"\n"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.read_bytes() != contents:
            raise HarnessError("update preview receipt conflicts with its digest")
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
    return digest


def _check_update_preview(state, digest, report):
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise HarnessError("apply requires the digest of a reviewed preview: --preview-digest <sha256>")
    path = state / "previews" / (digest + ".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise HarnessError("reviewed update preview is missing or unsafe")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessError("reviewed update preview could not be read") from error
    if (hashlib.sha256(_canonical_json(payload)).hexdigest() != digest
            or raw != _canonical_json(payload) + b"\n"
            or payload != {"schema_version": 1, "report": report}):
        raise HarnessError("release plan changed since preview; review a new preview before applying")


def update_runtime(*, apply=False, tag=None, preview_digest=None):
    if apply and not tag:
        raise HarnessError("apply requires the exact previewed tag: --apply --tag vX.Y.Z --preview-digest <sha256>")
    if apply and (not isinstance(preview_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", preview_digest)):
        raise HarnessError("apply requires the digest of a reviewed preview: --preview-digest <sha256>")
    release = release_by_tag(tag) if tag else latest_release()
    fingerprint, keyring = _release_trust()
    target_text = os.environ.get("CAPHE_RUNTIME")
    if not target_text:
        raise HarnessError("CAPHE_RUNTIME must identify the installed runtime")
    target = Path(target_text).expanduser().absolute()
    if target.resolve() == ROOT or (ROOT in target.resolve().parents):
        raise HarnessError("source checkout is not an installed runtime target")
    if not target.is_dir() or not (target / ".caphe-runtime.json").is_file():
        raise HarnessError("target is not an inventoried installed runtime")
    spec = importlib.util.spec_from_file_location("caphe_stack_install", ROOT / "tools" / "stack_install.py")
    stack_install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack_install)
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")).expanduser() / "caphe" / "updates"
    stack_install._outside_canonical_stores(state)
    stack_install._outside_git(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.stat().st_uid != os.getuid():
        raise HarnessError("update state directory is not owned by the current user")
    state.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="release-", dir=state) as temporary:
        stage, archive_digest, git_env = _stage_release(release["tag"], fingerprint, keyring, Path(temporary))
        stack_install = _load_staged_installer(stage)
        plan = stack_install.plan_runtime_install(stage, target)
        current_digest = stack_install._entries_digest(plan["previous_payload"])
        changes = {"added": [], "changed": [], "unchanged": [], "retired": []}
        previous = {item[0]: item[1] for item in plan["previous_payload"]}
        incoming = {item[0]: item[1] for item in plan["payload"]}
        for name, digest in incoming.items():
            changes["added" if name not in previous else "unchanged" if previous[name] == digest else "changed"].append(name)
        changes["retired"] = sorted(set(previous) - set(incoming))
        report = {"status": "planned", "release": release, "tag_signature_fingerprint": fingerprint,
                  "archive_sha256": archive_digest, "current_inventory_sha256": current_digest,
                  "new_inventory_sha256": plan["source_digest"], "changes": changes}
        if apply:
            _check_update_preview(state, preview_digest, report)
        else:
            report["preview_digest"] = _write_update_preview(state, report)
        if apply:
            inventory_root = state / "install-inventory"
            receipt = stack_install.apply_runtime_plan(plan, inventory_root=inventory_root)
            report.update(status="applied", verified=receipt["verified"],
                          receipt_path=receipt["receipt_path"], preview_digest=preview_digest)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor", help="inspect or initialize the harness environment")
    doctor_parser.add_argument("--config", default=str(default_config_path()))
    doctor_parser.add_argument("--apply", action="store_true", help="create the config template if absent")
    doctor_parser.add_argument("--probe", action="store_true", help="run one small live test for each enabled route; uses provider allowance")
    update_parser = sub.add_parser("update", help="preview a signed tagged runtime release")
    update_parser.add_argument("--apply", action="store_true", help="apply the verified release plan")
    update_parser.add_argument("--tag", help="exact stable release tag to plan or apply")
    update_parser.add_argument("--preview-digest", help="digest printed by the reviewed update preview")
    worker_parser = sub.add_parser("worker", help="run a bounded worker using an explicit route")
    worker_parser.add_argument("--config", default=str(default_config_path()))
    worker_parser.add_argument("--repo", default=".")
    worker_parser.add_argument("--category", required=True)
    worker_parser.add_argument("--brief-file", required=True)
    worker_parser.add_argument("--allow-write", action="append", default=[], help="repository-relative file or directory allowed to change")
    worker_parser.add_argument("--parent-run-id", help="optional coordinator or batch run id")
    worker_parser.add_argument("--retry-of", help="run id this task retries")
    worker_parser.add_argument("--execute", action="store_true", help="invoke the configured model and consume its allowance")
    batch_parser = sub.add_parser("batch", help="launch bounded independent CLI workers from a JSON task list")
    batch_parser.add_argument("--config", default=str(default_config_path()))
    batch_parser.add_argument("--tasks-file", required=True, help="JSON array of category, repo, and brief_file objects")
    batch_parser.add_argument("--parent-run-id", help="optional coordinator run id")
    batch_parser.add_argument("--execute", action="store_true", help="invoke enabled routes and consume their allowance")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(args.config, apply=args.apply, probe=args.probe)
        elif args.command == "update":
            result = update_runtime(apply=args.apply, tag=args.tag, preview_digest=args.preview_digest)
        elif args.command == "batch":
            config, _ = load_config(args.config)
            task_path = Path(args.tasks_file).expanduser()
            if task_path.is_symlink() or not task_path.is_file() or task_path.stat().st_size > 1024 * 1024:
                raise HarnessError("batch task file must be a regular JSON file under 1 MiB")
            try:
                tasks = json.loads(task_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json)
            except (json.JSONDecodeError, ValueError) as error:
                raise HarnessError("batch task file is not valid JSON") from error
            result = run_batch(config, tasks, execute=args.execute, parent_run_id=args.parent_run_id)
        else:
            config, _ = load_config(args.config)
            route = next((r for r in config["routes"] if r["category"] == args.category), None)
            if not route or not route["enabled"]:
                raise HarnessError("route is missing or disabled")
            brief_path = Path(args.brief_file)
            if brief_path.is_symlink() or not brief_path.is_file():
                raise HarnessError("brief file must be a regular file")
            if brief_path.stat().st_size > route["context_budget_tokens"] * 3:
                raise HarnessError("brief file exceeds the route context budget")
            result = run_worker(config, route, args.repo, brief_path.read_text(encoding="utf-8"),
                                execute=args.execute, allowed_writes=args.allow_write,
                                parent_run_id=args.parent_run_id, retry_of=args.retry_of)
        print(json.dumps(result, sort_keys=True))
        if args.command == "doctor":
            return 0
        if args.command == "batch":
            return 0 if result.get("status") == "completed" else 1
        if args.command == "worker":
            if result.get("status") == "planned":
                return 0
            return 0 if (result.get("status") == "completed" and result.get("route_verified") is True
                         and result.get("write_scope_verified", True) is True) else 1
        return 0 if (result.get("status") == "planned" or
                      result.get("status") == "applied" and result.get("verified") is True) else 1
    except (HarnessError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(json.dumps({"status": "error", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
