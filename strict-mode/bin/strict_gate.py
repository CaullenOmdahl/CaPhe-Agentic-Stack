#!/usr/bin/env python3
"""Deterministic affected/full verification planner for Strict Mode v3 (ADR-0004)."""

from __future__ import annotations

import argparse
import concurrent.futures
import functools
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any, Iterable, NamedTuple


MANIFEST_PATH = ".agent/strict-gate.json"
GIT_REPOSITORY_ENV_FALLBACK = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)


class ManifestError(ValueError):
    pass


class CommandSpec(NamedTuple):
    component: str
    name: str
    argv: tuple[str, ...]
    cwd: str = "."
    cache_allowed: bool = False
    cache_inputs: tuple[str, ...] = ()
    cache_env: tuple[str, ...] = ()
    toolchain: tuple[tuple[str, ...], ...] = ()
    timeout_seconds: float | None = None
    after: tuple[str, ...] = ()


@functools.lru_cache(maxsize=1)
def git_repository_environment_names() -> tuple[str, ...]:
    """Ask the active Git client for repository-local variables, with a portable fallback."""
    names = set(GIT_REPOSITORY_ENV_FALLBACK)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return tuple(sorted(names))
    if result.returncode == 0:
        names.update(result.stdout.split())
    return tuple(sorted(names))


def command_environment() -> dict[str, str]:
    """Return a child-check environment without the calling Git hook's repository state."""
    environment = os.environ.copy()
    for name in git_repository_environment_names():
        environment.pop(name, None)
    return environment


def _require_string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{label} must be a list of non-empty strings")
    if nonempty and not value:
        raise ManifestError(f"{label} must not be empty")
    return value


def validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ManifestError("manifest version must be 1")
    components = data.get("components")
    if not isinstance(components, list) or not components:
        raise ManifestError("components must be a non-empty list")
    names: set[str] = set()
    command_ids: set[tuple[str, str]] = set()
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise ManifestError(f"components[{index}] must be an object")
        name = component.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ManifestError(f"component name is missing or duplicated: {name!r}")
        names.add(name)
        _require_string_list(component.get("paths"), f"{name}.paths", nonempty=True)
        _require_string_list(component.get("depends_on", []), f"{name}.depends_on")
        commands = component.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ManifestError(f"{name}.commands must be a non-empty list")
        for command in commands:
            if not isinstance(command, dict):
                raise ManifestError(f"{name}.commands entries must be objects")
            command_name = command.get("name")
            argv = command.get("run")
            if not isinstance(command_name, str) or not command_name:
                raise ManifestError(f"{name} command name must be non-empty")
            if (name, command_name) in command_ids:
                raise ManifestError(f"duplicate command {name}:{command_name}")
            command_ids.add((name, command_name))
            _require_string_list(argv, f"{name}.{command_name}.run", nonempty=True)
            if type(command.get("parallel_safe", False)) is not bool:
                raise ManifestError(f"{name}.{command_name}.parallel_safe must be boolean")
            timeout = command.get("timeout_seconds")
            if timeout is not None and (
                isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0
            ):
                raise ManifestError(f"{name}.{command_name}.timeout_seconds must be positive and finite")
            if command.get("cache", False):
                _require_string_list(command.get("cache_inputs"), f"{name}.{command_name}.cache_inputs", nonempty=True)
                _require_string_list(command.get("cache_env"), f"{name}.{command_name}.cache_env")
                toolchain = command.get("toolchain")
                if not isinstance(toolchain, list) or not toolchain:
                    raise ManifestError(f"{name}.{command_name}.toolchain is required for caching")
                for probe in toolchain:
                    _require_string_list(probe, f"{name}.{command_name}.toolchain[]", nonempty=True)
        verification = component.get("dependency_verification", {"kind": "unverified"})
        if not isinstance(verification, dict) or not isinstance(verification.get("kind"), str):
            raise ManifestError(f"{name}.dependency_verification must declare kind")
        if verification["kind"] == "custom":
            _require_string_list(verification.get("command"), f"{name}.dependency_verification.command", nonempty=True)
    for component in components:
        for dependency in component.get("depends_on", []):
            if dependency not in names:
                raise ManifestError(f"{component['name']} depends on unknown component {dependency}")
    _check_dependency_cycles(components)
    return data


def _check_dependency_cycles(components: list[dict[str, Any]]) -> None:
    graph = {component["name"]: component.get("depends_on", []) for component in components}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ManifestError(f"dependency cycle includes {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.removeprefix("./")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def validate_path_coverage(data: dict[str, Any], tracked_paths: Iterable[str]) -> None:
    validate_manifest(data)
    patterns = [pattern for component in data["components"] for pattern in component["paths"]]
    patterns.extend(data.get("exclude_paths", []))
    uncovered = sorted(path for path in tracked_paths if not _matches(path, patterns))
    if uncovered:
        preview = ", ".join(uncovered[:8])
        raise ManifestError(f"tracked paths are not covered by the manifest: {preview}")


def _verification_proven(
    component: dict[str, Any],
    component_count: int,
    verified_dependencies: set[str],
) -> bool:
    kind = component.get("dependency_verification", {}).get("kind", "unverified")
    if kind == "single-component":
        return component_count == 1
    return kind == "custom" and component["name"] in verified_dependencies


def verify_dependency_completeness(root: Path, data: dict[str, Any]) -> set[str]:
    """Run declared custom verifiers; labels alone never enable affected scoping."""
    verified: set[str] = set()
    for component in data["components"]:
        verification = component.get("dependency_verification", {})
        if verification.get("kind") != "custom":
            continue
        try:
            result = subprocess.run(
                verification["command"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=command_environment(),
            )
        except OSError:
            continue
        if result.returncode == 0:
            verified.add(component["name"])
    return verified


def _command_specs(component: dict[str, Any], *, completion: bool) -> list[CommandSpec]:
    result: list[CommandSpec] = []
    for command in component["commands"]:
        result.append(
            CommandSpec(
                component=component["name"],
                name=command["name"],
                argv=tuple(command["run"]),
                cwd=command.get("cwd", "."),
                cache_allowed=bool(command.get("cache", False)) and not completion,
                cache_inputs=tuple(command.get("cache_inputs", [])),
                cache_env=tuple(command.get("cache_env", [])),
                toolchain=tuple(tuple(probe) for probe in command.get("toolchain", [])),
                timeout_seconds=command.get("timeout_seconds"),
                after=() if command.get("parallel_safe", False) else tuple(
                    f"{prior.component}:{prior.name}" for prior in result
                ),
            )
        )
    return result


def build_plan(
    data: dict[str, Any],
    changed_paths: Iterable[str],
    *,
    mode: str,
    verified_dependencies: set[str] | None = None,
) -> list[CommandSpec]:
    validate_manifest(data)
    components = data["components"]
    changed = [path.removeprefix("./") for path in changed_paths]
    completion = mode in {"completion", "full"}
    force_full = completion or MANIFEST_PATH in changed
    known_patterns = [pattern for component in components for pattern in component["paths"]]
    if any(not _matches(path, known_patterns) for path in changed if path != MANIFEST_PATH):
        force_full = True
    verified_dependencies = verified_dependencies or set()
    if not force_full and not all(
        _verification_proven(component, len(components), verified_dependencies) for component in components
    ):
        force_full = True

    selected: set[str]
    if force_full:
        selected = {component["name"] for component in components}
    else:
        selected = {
            component["name"]
            for component in components
            if any(_matches(path, component["paths"]) for path in changed)
        }
        changed_selection = True
        while changed_selection:
            changed_selection = False
            for component in components:
                if component["name"] not in selected and any(
                    dependency in selected for dependency in component.get("depends_on", [])
                ):
                    selected.add(component["name"])
                    changed_selection = True
    plan = [
        command
        for component in components
        if component["name"] in selected
        for command in _command_specs(component, completion=completion)
    ]
    # A selected dependent component waits for selected prerequisite components.
    dependencies = {component["name"]: component.get("depends_on", []) for component in components}
    return [command._replace(after=tuple(dict.fromkeys((*command.after, *(
        f"{prior.component}:{prior.name}" for prior in plan
        if prior.component in dependencies[command.component]
    ))))) for command in plan]


def _hash_file(root: Path, path: Path, digest: "hashlib._Hash") -> None:
    """Bind regular-file bytes and mode without following any input symlink."""
    relative = path.relative_to(root)
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ManifestError("cache inputs must be regular files")
            name = os.fsencode(str(path))
            digest.update(len(name).to_bytes(8, "big") + name)
            digest.update(f"{before.st_mode}:{before.st_size}\0".encode())
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(handle.fileno())
            identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if identity(before) != identity(after):
                raise ManifestError("cache input changed while hashing")
    except OSError:
        raise ManifestError("cache input is unreadable or uses a symlink") from None
    finally:
        os.close(parent)


def cache_key(root: Path, command: CommandSpec, manifest_identity: str) -> str:
    if not command.cache_allowed:
        raise ManifestError("cache key requested for a non-cacheable command")
    if not command.cache_inputs or not command.toolchain:
        raise ManifestError("cache identity requires input files and toolchain probes")
    root = root.resolve()
    digest = hashlib.sha256(b"caphe-feedback-cache-v2\0")
    digest.update(manifest_identity.encode())
    digest.update(json.dumps(command._asdict(), sort_keys=True).encode())
    # Probe first, so any resulting input mutation is reflected in the file hashes below.
    for probe in command.toolchain:
        try:
            result = subprocess.run(
                probe, cwd=root / command.cwd, text=True, capture_output=True,
                check=False, env=command_environment(), timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            raise ManifestError("cache toolchain probe could not complete") from None
        if result.returncode != 0:
            raise ManifestError("cache toolchain probe failed")
        digest.update(json.dumps(probe).encode())
        for output in (result.stdout, result.stderr):
            payload = output.encode()
            digest.update(len(payload).to_bytes(8, "big") + payload)
    for pattern in command.cache_inputs:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ManifestError("cache inputs must stay inside the repository")
        matches = sorted(root.glob(pattern))
        if not matches:
            raise ManifestError("cache input pattern has no matches")
        for path in matches:
            _hash_file(root, path, digest)
    for name in command.cache_env:
        digest.update(name.encode())
        digest.update(os.environ.get(name, "<unset>").encode())
    return digest.hexdigest()


def _run_one(root: Path, command: CommandSpec, manifest_identity: str, cache_dir: Path) -> tuple[CommandSpec, int, str, bool]:
    cache_file: Path | None = None
    if command.cache_allowed:
        key = cache_key(root, command, manifest_identity)
        cache_file = cache_dir / f"{key}.ok"
        if cache_file.is_file():
            return command, 0, "", True
    try:
        process = subprocess.Popen(
            command.argv, cwd=root / command.cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=command_environment(), start_new_session=(os.name == "posix"),
        )
    except OSError as error:
        return command, 127, f"command could not start: {error}", False
    try:
        stdout, stderr = process.communicate(timeout=command.timeout_seconds)
        code = process.returncode
        output = stdout + stderr
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        code = 124
        output = stdout + stderr + f"\ncommand timeout after {command.timeout_seconds}s"
    if code == 0 and cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        lock = cache_file.with_suffix(".lock")
        try:
            lock.mkdir()
            with tempfile.NamedTemporaryFile("w", dir=cache_file.parent, delete=False) as handle:
                handle.write("ok\n")
                tmp = Path(handle.name)
            os.replace(tmp, cache_file)
        except FileExistsError:
            pass
        finally:
            try:
                lock.rmdir()
            except OSError:
                pass
    return command, code, output, False


def _git_bytes(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=check,
        env=command_environment(), timeout=30,
    )
    return result.stdout


def changed_paths(root: Path) -> list[str]:
    """Cover the actual working state that checks execute, including unstaged and new paths."""
    paths = set(_git_paths(root, "diff", "--cached", "--no-renames", "--name-only"))
    paths.update(_git_paths(root, "diff", "--no-renames", "--name-only"))
    paths.update(_git_paths(root, "ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def snapshot_identity(root: Path) -> dict[str, Any]:
    flags = _git_bytes(root, "ls-files", "-v", "-z").split(b"\0")
    if any(record[:1].islower() or record.startswith(b"S ") for record in flags if record):
        raise ManifestError("snapshot incomplete: assume-unchanged or skip-worktree flags hide working files")
    index = _git_bytes(root, "ls-files", "--stage", "-z").split(b"\0")
    if any(record.startswith(b"160000 ") for record in index):
        raise ManifestError("snapshot incomplete: submodule working content is unsupported")
    revision = _git_bytes(root, "rev-parse", "--verify", "HEAD", check=False).decode().strip() or None
    digest = hashlib.sha256(b"caphe-working-snapshot-v1\0")
    digest.update((revision or "unborn").encode())
    for args in (
        ("diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"),
        ("diff", "--binary", "--no-ext-diff", "--no-textconv"),
    ):
        payload = _git_bytes(root, *args)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    for relative in sorted(_git_paths(root, "ls-files", "--others", "--exclude-standard")):
        path = root / relative
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ManifestError("snapshot path has a symlinked parent")
        name = os.fsencode(relative)
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        if path.is_symlink():
            digest.update(b"link\0" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ManifestError("snapshot path is not a regular file")
                digest.update(f"file:{before.st_mode & 0o777}:{before.st_size}\0".encode())
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
                after = os.fstat(handle.fileno())
                if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise ManifestError("snapshot path changed during hashing")
        else:
            raise ManifestError(f"snapshot path changed or has unsupported type: {relative}")
    return {"revision": revision, "snapshot_digest": digest.hexdigest(), "dirty": bool(changed_paths(root))}


def _report_destination(path: Path) -> Path:
    """Diagnostics stay owner-only outside repositories; they never attest their own authority."""
    path = path.expanduser().absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ManifestError("report destination must not contain a symlink")
    if '.git' in path.parts or any(left == '.codex' and right in ('sessions', 'memories')
                                 for left, right in zip(path.parts, path.parts[1:])):
        raise ManifestError("diagnostics cannot replace Git metadata or canonical records")
    nearest = path.parent
    while not nearest.exists():
        nearest = nearest.parent
    in_git = subprocess.run(
        ["git", "-C", str(nearest), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, env=command_environment(), timeout=10,
    )
    if in_git.returncode == 0 and in_git.stdout.strip() == "true":
        raise ManifestError("diagnostic report must be outside Git worktrees")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_stat = path.parent.stat()
    if parent_stat.st_mode & 0o077 or parent_stat.st_uid != os.getuid():
        raise ManifestError("diagnostic report parent must be owner-only")
    return path


def execute_plan(
    root: Path, plan: list[CommandSpec], manifest_identity: str, jobs: int,
    *, report_path: Path | None = None, mode: str = "affected",
) -> int:
    destination = _report_destination(report_path) if report_path is not None else None
    before = snapshot_identity(root)
    started = time.monotonic()
    outcomes = []
    cache_dir = root / ".agent" / "cache" / "strict-gate"
    failures = 0
    by_id = {f"{command.component}:{command.name}": command for command in plan}
    if len(by_id) != len(plan) or any(set(command.after) - set(by_id) for command in plan):
        raise ManifestError("execution plan has duplicate or missing command dependencies")
    pending = dict(by_id)
    finished = {}
    running = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        while pending or running:
            for identifier, command in list(pending.items()):
                if not set(command.after).issubset(finished):
                    continue
                if any(finished[prior][1] != 0 for prior in command.after):
                    finished[identifier] = (command, 126, "prerequisite check failed; command was not run", False)
                    del pending[identifier]
                elif len(running) < max(1, jobs):
                    running[executor.submit(_run_one, root, command, manifest_identity, cache_dir)] = identifier
                    del pending[identifier]
            if running:
                completed, _ = concurrent.futures.wait(running, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in completed:
                    identifier = running.pop(future)
                    try:
                        finished[identifier] = future.result()
                    except Exception as error:
                        finished[identifier] = (by_id[identifier], 125, f"check execution failed: {error}", False)
            elif pending:
                # Failed prerequisites can unblock further skipped descendants on the next pass.
                if any(set(command.after).issubset(finished) for command in pending.values()):
                    continue
                raise ManifestError("execution plan contains a dependency cycle")
        for command in plan:
            command, code, output, cached = finished[f"{command.component}:{command.name}"]
            outcomes.append({
                "component": command.component, "name": command.name,
                "argv": list(command.argv), "cwd": command.cwd,
                "after": list(command.after),
                "exit_code": code, "cached": cached,
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            })
            label = f"{command.component}:{command.name}"
            if cached:
                print(f"CACHE {label}")
            elif code == 0:
                print(f"PASS  {label}")
            else:
                failures += 1
                print(f"FAIL  {label}", file=sys.stderr)
                if output:
                    print(output.rstrip(), file=sys.stderr)
    after = snapshot_identity(root)
    stale = before != after
    if stale:
        failures += 1
        print("FAIL  source changed while checks ran; rerun against the resulting snapshot", file=sys.stderr)
    if destination is not None:
        report = {
            "schema_version": 1, "kind": "diagnostic-gate-report", "authoritative": False,
            "authority_reason": "candidate execution has no independently trusted executor",
            "mode": mode, "manifest_digest": manifest_identity,
            "source_before": before, "source_after": after, "stale_source": stale,
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "commands": outcomes, "exit_code": 1 if failures else 0,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
        with tempfile.NamedTemporaryFile("w", dir=destination.parent, delete=False, encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return 1 if failures else 0


def _git_paths(root: Path, *args: str) -> list[str]:
    return [os.fsdecode(path) for path in _git_bytes(root, *args, "-z").split(b"\0") if path]


def _relative_cwd(root: Path, manifest: Path) -> str:
    parent = manifest.parent.relative_to(root)
    return "." if str(parent) == "." else str(parent)


def _has_pytest_configuration(project_root: Path) -> bool:
    """Detect pytest configuration that makes the project root a test entrypoint."""
    if (project_root / "pytest.ini").is_file() or (project_root / "conftest.py").is_file():
        return True
    if (project_root / "tests" / "conftest.py").is_file():
        return True

    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(errors="replace"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        tool = data.get("tool", {}) if isinstance(data, dict) else {}
        if isinstance(tool, dict) and isinstance(tool.get("pytest"), dict):
            return True

    setup_cfg = project_root / "setup.cfg"
    if setup_cfg.is_file() and re.search(
        r"(?im)^\s*\[tool:pytest\]\s*$", setup_cfg.read_text(errors="replace")
    ):
        return True
    tox_ini = project_root / "tox.ini"
    return bool(
        tox_ini.is_file()
        and re.search(
            r"(?im)^\s*(?:commands\s*=\s*)?.*\bpytest\b",
            tox_ini.read_text(errors="replace"),
        )
    )


def _declares_pytest(project_root: Path) -> bool:
    """Detect an explicit pytest contract without importing project dependencies."""
    if _has_pytest_configuration(project_root):
        return True

    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(errors="replace"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        project = data.get("project", {}) if isinstance(data, dict) else {}
        dependency_groups: list[Any] = []
        if isinstance(project, dict):
            dependency_groups.append(project.get("dependencies", []))
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                dependency_groups.extend(optional.values())
        standardized_groups = data.get("dependency-groups", {})
        if isinstance(standardized_groups, dict):
            dependency_groups.extend(standardized_groups.values())
        if any(
            isinstance(group, list)
            and any(
                isinstance(item, str)
                and re.search(
                    r"(?i)(?:^|[^A-Za-z0-9_-])pytest(?:$|[^A-Za-z0-9_-])",
                    item,
                )
                for item in group
            )
            for group in dependency_groups
        ):
            return True

        tool = data.get("tool", {}) if isinstance(data, dict) else {}
        poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
        poetry_dependencies: list[Any] = []
        if isinstance(poetry, dict):
            poetry_dependencies.extend(
                (poetry.get("dependencies", {}), poetry.get("dev-dependencies", {}))
            )
            poetry_groups = poetry.get("group", {})
            if isinstance(poetry_groups, dict):
                poetry_dependencies.extend(
                    group.get("dependencies", {})
                    for group in poetry_groups.values()
                    if isinstance(group, dict)
                )
        if any(
            isinstance(dependencies, dict)
            and any(name.lower().replace("_", "-") == "pytest" for name in dependencies)
            for dependencies in poetry_dependencies
        ):
            return True

    for requirements in project_root.glob("requirements*.txt"):
        if requirements.is_file() and re.search(
            r"(?im)^\s*pytest(?:\s|$|[<>=!~;\[])",
            requirements.read_text(errors="replace"),
        ):
            return True
    return False


def _python_test_runner(root: Path, python_root: Path) -> str:
    """Use the nearest project declaration; plain test trees retain unittest."""
    current = python_root
    while True:
        if _declares_pytest(current):
            return "pytest"
        if any(
            (current / marker).is_file()
            for marker in ("pyproject.toml", "setup.py", "setup.cfg", "tox.ini")
        ):
            return "unittest"
        if current == root:
            return "unittest"
        current = current.parent


def discover_default_manifest(root: Path) -> dict[str, Any]:
    """Create a safe single-component manifest; repositories can later split it for speed."""
    commands: list[dict[str, Any]] = [
        {"name": "diff-check", "run": ["git", "diff", "--cached", "--check"]},
    ]
    command_names = {"diff-check"}

    pubspecs = sorted(path for path in root.rglob("pubspec.yaml") if ".dart_tool" not in path.parts and "build" not in path.parts)
    workspace_members: set[Path] = set()
    root_pubspec = root / "pubspec.yaml"
    if root_pubspec in pubspecs:
        lines = root_pubspec.read_text(errors="replace").splitlines()
        in_workspace = False
        for line in lines:
            if line.startswith("workspace:"):
                in_workspace = True
                continue
            if in_workspace and line and not line.startswith((" ", "\t")):
                in_workspace = False
            if in_workspace:
                match = re.match(r"\s*-\s+(.+?)\s*$", line)
                if match:
                    workspace_members.add((root / match.group(1)).resolve())
    if workspace_members:
        pubspecs = [path for path in pubspecs if path != root_pubspec]
    for pubspec in pubspecs:
        cwd = _relative_cwd(root, pubspec)
        text = pubspec.read_text(errors="replace")
        tool = "flutter" if re.search(r"sdk:\s*flutter", text) else "dart"
        for action in ("analyze", "test"):
            name = f"{tool}-{action}-{cwd.replace('/', '-')}"
            if name not in command_names:
                commands.append({"name": name, "run": [tool, action], "cwd": cwd})
                command_names.add(name)

    for package in sorted(root.rglob("package.json")):
        if any(part in {"node_modules", "build", "dist", ".svelte-kit"} for part in package.parts):
            continue
        try:
            scripts = json.loads(package.read_text()).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            continue
        cwd = _relative_cwd(root, package)
        package_manager = "pnpm" if (package.parent / "pnpm-lock.yaml").exists() else "npm"
        for script_name in ("test", "lint", "typecheck"):
            if script_name not in scripts:
                continue
            name = f"{package_manager}-{script_name}-{cwd.replace('/', '-')}"
            run = [package_manager, script_name] if package_manager == "pnpm" else ["npm", "run", script_name, "--silent"]
            commands.append({"name": name, "run": run, "cwd": cwd})

    cargo_manifests = [
        path for path in sorted(root.rglob("Cargo.toml")) if "target" not in path.parts
    ]
    cargo_workspaces = {
        path
        for path in cargo_manifests
        if re.search(r"(?m)^\s*\[workspace\]\s*$", path.read_text(errors="replace"))
    }
    workspace_rules: dict[Path, tuple[list[str], list[str]]] = {}
    for workspace in cargo_workspaces:
        try:
            workspace_data = tomllib.loads(workspace.read_text(errors="replace")).get("workspace", {})
        except (OSError, tomllib.TOMLDecodeError):
            workspace_data = {}
        members = workspace_data.get("members", []) if isinstance(workspace_data, dict) else []
        excludes = workspace_data.get("exclude", []) if isinstance(workspace_data, dict) else []
        workspace_rules[workspace] = (
            [item for item in members if isinstance(item, str)],
            [item for item in excludes if isinstance(item, str)],
        )

    def covered_by_workspace(path: Path) -> bool:
        for workspace, (members, excludes) in workspace_rules.items():
            if workspace.parent not in path.parents:
                continue
            relative = path.parent.relative_to(workspace.parent).as_posix()
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in excludes):
                continue
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in members):
                return True
        return False

    cargo_roots = [
        path for path in cargo_manifests if path in cargo_workspaces or not covered_by_workspace(path)
    ]
    for cargo in cargo_roots:
        cwd = _relative_cwd(root, cargo)
        suffix = cwd.replace("/", "-")
        commands.extend(
            [
                {"name": f"cargo-fmt-{suffix}", "run": ["cargo", "fmt", "--all", "--check"], "cwd": cwd},
                {"name": f"cargo-clippy-{suffix}", "run": ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"], "cwd": cwd},
                {"name": f"cargo-test-{suffix}", "run": ["cargo", "test", "--workspace"], "cwd": cwd},
            ]
        )
    for go_mod in sorted(root.rglob("go.mod")):
        if any(part in {"vendor", "build", "dist"} for part in go_mod.parts):
            continue
        cwd = _relative_cwd(root, go_mod)
        suffix = cwd.replace("/", "-")
        commands.append({"name": f"go-test-{suffix}", "run": ["go", "test", "./..."], "cwd": cwd})
    excluded_python_parts = {
        ".git",
        ".tox",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
    python_project_roots = {root}
    for pattern in (
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "requirements*.txt",
    ):
        python_project_roots.update(
            config.parent
            for config in root.rglob(pattern)
            if not any(part in excluded_python_parts for part in config.parts)
        )

    def owning_python_project(test_module: Path) -> Path:
        candidates = [
            project_root
            for project_root in python_project_roots
            if project_root == test_module.parent or project_root in test_module.parents
        ]
        return max(candidates, key=lambda path: len(path.parts))

    python_test_roots = {
        owning_python_project(tests)
        for tests in root.rglob("tests")
        if tests.is_dir() and not any(part in excluded_python_parts for part in tests.parts)
    }
    root_level_test_roots = {
        owning_python_project(test_module)
        for test_module in root.rglob("test*.py")
        if test_module.is_file()
        and not any(part in excluded_python_parts for part in test_module.parts)
        and "tests" not in test_module.relative_to(root).parts[:-1]
    }
    python_test_roots.update(root_level_test_roots)
    pytest_project_roots = {
        config.parent
        for pattern in (
            "pyproject.toml",
            "pytest.ini",
            "setup.cfg",
            "tox.ini",
            "requirements*.txt",
        )
        for config in root.rglob(pattern)
        if not any(part in excluded_python_parts for part in config.parts)
        and _declares_pytest(config.parent)
    }
    python_test_roots.update(pytest_project_roots)
    for python_root in sorted(python_test_roots):
        cwd = "." if python_root == root else python_root.relative_to(root).as_posix()
        suffix = "" if cwd == "." else f"-{cwd.replace('/', '-')}"
        runner = _python_test_runner(root, python_root)
        nested_roots = sorted(
            candidate
            for candidate in python_test_roots
            if candidate != python_root and python_root in candidate.parents
        )
        command = (
            {
                "name": f"python-pytest{suffix}",
                "run": [
                    "python3",
                    "-m",
                    "pytest",
                    *[
                        f"--ignore={candidate.relative_to(python_root).as_posix()}"
                        for candidate in nested_roots
                    ],
                ],
            }
            if runner == "pytest"
            else {
                "name": f"python-unittest{suffix}",
                "run": [
                    "python3",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests" if (python_root / "tests").is_dir() else ".",
                    "-v",
                ],
            }
        )
        if cwd != ".":
            command["cwd"] = cwd
        commands.append(command)

    return {
        "version": 1,
        "components": [
            {
                "name": "repository",
                "paths": ["**"],
                "depends_on": [],
                "dependency_verification": {"kind": "single-component"},
                "commands": commands,
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=MANIFEST_PATH)
    parser.add_argument("--mode", choices=("affected", "completion", "full", "plan"), default="affected")
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    parser.add_argument("--write-default-manifest", action="store_true")
    parser.add_argument("--report", type=Path, help="owner-only diagnostic JSON outside Git; never an authoritative receipt")
    args = parser.parse_args(argv)
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    manifest_path = root / args.manifest
    if args.write_default_manifest:
        if manifest_path.exists():
            print(f"manifest already exists: {manifest_path}")
            return 0
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(discover_default_manifest(root), indent=2) + "\n"
        with tempfile.NamedTemporaryFile("w", dir=manifest_path.parent, delete=False) as handle:
            handle.write(payload)
            tmp = Path(handle.name)
        os.replace(tmp, manifest_path)
        print(f"created {manifest_path}")
        return 0
    try:
        raw = manifest_path.read_bytes()
        data = validate_manifest(json.loads(raw))
        tracked = _git_paths(root, "ls-files")
        validate_path_coverage(data, tracked)
        changed = sorted(set(args.changed) | set(changed_paths(root)))
        mode = "affected" if args.mode == "plan" else args.mode
        verified_dependencies = (
            verify_dependency_completeness(root, data) if mode == "affected" else set()
        )
        plan = build_plan(
            data,
            changed,
            mode=mode,
            verified_dependencies=verified_dependencies,
        )
    except (OSError, json.JSONDecodeError, ManifestError, subprocess.CalledProcessError) as error:
        print(f"STRICT GATE CONFIG ERROR: {error}", file=sys.stderr)
        return 2
    if args.mode == "plan":
        print(json.dumps([command._asdict() for command in plan], indent=2))
        return 0
    try:
        code = execute_plan(root, plan, hashlib.sha256(raw).hexdigest(), args.jobs,
                            report_path=args.report, mode=args.mode)
    except (OSError, ManifestError, subprocess.SubprocessError) as error:
        print(f"STRICT GATE EXECUTION ERROR: {error}", file=sys.stderr)
        return 2
    if code:
        print("RED", file=sys.stderr)
    elif args.mode == "affected":
        print("FAST GREEN — focused feedback only; run --mode completion before done")
    else:
        print("GREEN")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
