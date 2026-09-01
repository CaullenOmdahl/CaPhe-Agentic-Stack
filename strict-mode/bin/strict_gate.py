#!/usr/bin/env python3
"""Deterministic affected/full verification planner for Strict Mode v2 (ADR-0001)."""

from __future__ import annotations

import argparse
import concurrent.futures
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Iterable, NamedTuple


MANIFEST_PATH = ".agent/strict-gate.json"


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
    return [
        command
        for component in components
        if component["name"] in selected
        for command in _command_specs(component, completion=completion)
    ]


def _hash_file(path: Path, digest: "hashlib._Hash") -> None:
    digest.update(str(path).encode())
    if not path.is_file():
        digest.update(b"<missing>")
        return
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)


def cache_key(root: Path, command: CommandSpec, manifest_identity: str) -> str:
    if not command.cache_allowed:
        raise ManifestError("cache key requested for a non-cacheable command")
    digest = hashlib.sha256()
    digest.update(manifest_identity.encode())
    digest.update(json.dumps(command._asdict(), sort_keys=True).encode())
    for pattern in command.cache_inputs:
        matches = sorted(root.glob(pattern))
        if not matches:
            digest.update(f"missing:{pattern}".encode())
        for path in matches:
            _hash_file(path, digest)
    for name in command.cache_env:
        digest.update(name.encode())
        digest.update(os.environ.get(name, "<unset>").encode())
    for probe in command.toolchain:
        result = subprocess.run(probe, cwd=root, text=True, capture_output=True, check=False)
        digest.update(json.dumps(probe).encode())
        digest.update(str(result.returncode).encode())
        digest.update(result.stdout.encode())
        digest.update(result.stderr.encode())
    return digest.hexdigest()


def _run_one(root: Path, command: CommandSpec, manifest_identity: str, cache_dir: Path) -> tuple[CommandSpec, int, str, bool]:
    cache_file: Path | None = None
    if command.cache_allowed:
        key = cache_key(root, command, manifest_identity)
        cache_file = cache_dir / f"{key}.ok"
        if cache_file.is_file():
            return command, 0, "", True
    result = subprocess.run(command.argv, cwd=root / command.cwd, text=True, capture_output=True, check=False)
    output = result.stdout + result.stderr
    if result.returncode == 0 and cache_file is not None:
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
    return command, result.returncode, output, False


def execute_plan(root: Path, plan: list[CommandSpec], manifest_identity: str, jobs: int) -> int:
    cache_dir = root / ".agent" / "cache" / "strict-gate"
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        futures = [executor.submit(_run_one, root, command, manifest_identity, cache_dir) for command in plan]
        for future in futures:
            command, code, output, cached = future.result()
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
    return 1 if failures else 0


def _git_paths(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


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
    python_test_roots = {
        tests.parent
        for tests in root.rglob("tests")
        if tests.is_dir() and not any(part in excluded_python_parts for part in tests.parts)
    }
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
        command = (
            {
                "name": f"python-pytest{suffix}",
                "run": [
                    "python3",
                    "-m",
                    "pytest",
                ],
            }
            if runner == "pytest"
            else {
                "name": f"python-unittest{suffix}",
                "run": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
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
        changed = args.changed or _git_paths(root, "diff", "--cached", "--name-only", "--diff-filter=ACMRD")
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
    code = execute_plan(root, plan, hashlib.sha256(raw).hexdigest(), args.jobs)
    if code:
        print("RED", file=sys.stderr)
    elif args.mode == "affected":
        print("FAST GREEN — focused feedback only; run --mode completion before done")
    else:
        print("GREEN")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
