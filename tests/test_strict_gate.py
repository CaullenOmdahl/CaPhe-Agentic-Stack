import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).parents[1] / "strict-mode" / "bin" / "strict_gate.py"
SPEC = importlib.util.spec_from_file_location("strict_gate", MODULE_PATH)
strict_gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(strict_gate)


def manifest(components):
    return {"version": 1, "components": components}


def component(name, paths, *, depends_on=None, verification="single-component"):
    return {
        "name": name,
        "paths": paths,
        "depends_on": depends_on or [],
        "dependency_verification": {"kind": verification},
        "commands": [{"name": "test", "run": ["python3", "-c", "print('ok')"]}],
    }


class StrictGatePlanTests(unittest.TestCase):
    def test_child_checks_do_not_inherit_calling_git_hook_repository_state(self):
        command = strict_gate.CommandSpec(
            component="a",
            name="environment",
            argv=(
                "python3",
                "-c",
                "import os; raise SystemExit(any(name in os.environ for name in "
                "('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_PREFIX', 'GIT_WORK_TREE')))",
            ),
        )
        inherited = {name: os.environ.get(name) for name in strict_gate.GIT_REPOSITORY_ENV}
        try:
            for name in strict_gate.GIT_REPOSITORY_ENV:
                os.environ[name] = f"inherited-{name.lower()}"
            with tempfile.TemporaryDirectory() as tmp:
                _, returncode, output, _ = strict_gate._run_one(
                    Path(tmp), command, "manifest", Path(tmp) / "cache"
                )
        finally:
            for name, value in inherited.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(returncode, 0, output)

    def test_completion_always_runs_every_command_uncached(self):
        data = manifest([
            component("a", ["a/**"]),
            component("b", ["b/**"]),
        ])
        plan = strict_gate.build_plan(data, ["a/file.py"], mode="completion")
        self.assertEqual([item.component for item in plan], ["a", "b"])
        self.assertTrue(all(not item.cache_allowed for item in plan))

    def test_affected_mode_escalates_when_dependency_completeness_is_unproven(self):
        data = manifest([
            component("a", ["a/**"], verification="unverified"),
            component("b", ["b/**"]),
        ])
        plan = strict_gate.build_plan(data, ["a/file.py"], mode="affected")
        self.assertEqual([item.component for item in plan], ["a", "b"])

    def test_custom_dependency_verifier_must_actually_pass_before_scoping(self):
        a = component("a", ["a/**"], verification="custom")
        b = component("b", ["b/**"], verification="custom")
        a["dependency_verification"]["command"] = ["python3", "-c", "raise SystemExit(0)"]
        b["dependency_verification"]["command"] = ["python3", "-c", "raise SystemExit(0)"]
        data = manifest([a, b])
        unverified = strict_gate.build_plan(data, ["a/file.py"], mode="affected")
        self.assertEqual([item.component for item in unverified], ["a", "b"])
        verified = strict_gate.build_plan(
            data,
            ["a/file.py"],
            mode="affected",
            verified_dependencies={"a", "b"},
        )
        self.assertEqual([item.component for item in verified], ["a"])

    def test_custom_dependency_verifier_result_is_measured(self):
        passing = component("passing", ["passing/**"], verification="custom")
        failing = component("failing", ["failing/**"], verification="custom")
        passing["dependency_verification"]["command"] = ["python3", "-c", "raise SystemExit(0)"]
        failing["dependency_verification"]["command"] = ["python3", "-c", "raise SystemExit(1)"]
        with tempfile.TemporaryDirectory() as tmp:
            verified = strict_gate.verify_dependency_completeness(Path(tmp), manifest([passing, failing]))
        self.assertEqual(verified, {"passing"})

    def test_affected_mode_propagates_to_consumers(self):
        data = manifest([
            component("core", ["core/**"]),
            component("app", ["app/**"], depends_on=["core"]),
        ])
        plan = strict_gate.build_plan(data, ["core/lib.py"], mode="affected")
        self.assertEqual([item.component for item in plan], ["core", "app"])

    def test_manifest_requires_nonempty_commands_and_known_dependencies(self):
        bad = manifest([{ "name": "a", "paths": ["a/**"], "commands": [] }])
        with self.assertRaises(strict_gate.ManifestError):
            strict_gate.validate_manifest(bad)
        bad_dep = manifest([component("a", ["a/**"], depends_on=["missing"])])
        with self.assertRaises(strict_gate.ManifestError):
            strict_gate.validate_manifest(bad_dep)

    def test_uncovered_tracked_path_blocks_instead_of_silently_planning(self):
        data = manifest([component("a", ["a/**"])])
        with self.assertRaises(strict_gate.ManifestError):
            strict_gate.validate_path_coverage(data, ["a/file.py", "unknown/file.py"])

    def test_manifest_change_forces_full_plan(self):
        data = manifest([component("a", ["a/**"]), component("b", ["b/**"])])
        plan = strict_gate.build_plan(data, [".agent/strict-gate.json"], mode="affected")
        self.assertEqual([item.component for item in plan], ["a", "b"])

    def test_cache_key_includes_declared_environment_toolchain_and_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "input.txt").write_text("one")
            command = strict_gate.CommandSpec(
                component="a",
                name="test",
                argv=("python3", "-c", "print('ok')"),
                cwd=".",
                cache_allowed=True,
                cache_inputs=("input.txt",),
                cache_env=("STRICT_TEST_VALUE",),
                toolchain=(("python3", "--version"),),
            )
            old = os.environ.get("STRICT_TEST_VALUE")
            try:
                os.environ["STRICT_TEST_VALUE"] = "one"
                first = strict_gate.cache_key(root, command, "manifest")
                os.environ["STRICT_TEST_VALUE"] = "two"
                second = strict_gate.cache_key(root, command, "manifest")
            finally:
                if old is None:
                    os.environ.pop("STRICT_TEST_VALUE", None)
                else:
                    os.environ["STRICT_TEST_VALUE"] = old
            self.assertNotEqual(first, second)

    def test_default_manifest_checks_the_staged_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = strict_gate.discover_default_manifest(Path(tmp))
        diff_check = next(
            command
            for command in data["components"][0]["commands"]
            if command["name"] == "diff-check"
        )
        self.assertEqual(diff_check["run"], ["git", "diff", "--cached", "--check"])

    def test_default_manifest_keeps_python_tests_in_hybrid_dart_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pubspec.yaml").write_text("name: hybrid\nenvironment:\n  sdk: ^3.0.0\n")
            (root / "tests").mkdir()
            data = strict_gate.discover_default_manifest(root)
        names = {command["name"] for command in data["components"][0]["commands"]}
        self.assertIn("dart-test-.", names)
        self.assertIn("python-unittest", names)

    def test_default_manifest_discovers_nested_python_test_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            (backend / "tests").mkdir(parents=True)
            (backend / "pyproject.toml").write_text("[project]\nname='backend'\nversion='0.1.0'\n")
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-unittest")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-unittest-backend",
                    "run": ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"],
                    "cwd": "backend",
                }
            ],
        )

    def test_default_manifest_uses_declared_pytest_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "pyproject.toml").write_text(
                "[project]\nname='pytest-project'\nversion='0.1.0'\n"
                "[tool.pytest.ini_options]\ntestpaths=['tests']\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-pytest",
                    "run": ["python3", "-m", "pytest"],
                }
            ],
        )

    def test_default_manifest_honors_configured_pytest_testpaths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "spec").mkdir()
            (root / "pyproject.toml").write_text(
                "[project]\nname='pytest-project'\nversion='0.1.0'\n"
                "[tool.pytest.ini_options]\ntestpaths=['tests', 'spec']\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-pytest",
                    "run": ["python3", "-m", "pytest"],
                }
            ],
        )

    def test_default_manifest_detects_standard_dependency_group_pytest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "pyproject.toml").write_text(
                "[project]\nname='pytest-project'\nversion='0.1.0'\n"
                "[dependency-groups]\ndev=['pytest>=8']\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(python_commands[0]["name"], "python-pytest")

    def test_default_manifest_schedules_dependency_declared_pytest_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_failure.py").write_text("def test_failure():\n    assert False\n")
            (root / "pyproject.toml").write_text(
                "[project]\nname='pytest-project'\nversion='0.1.0'\n"
                "[dependency-groups]\ndev=['pytest>=8']\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [{"name": "python-pytest", "run": ["python3", "-m", "pytest"]}],
        )

    def test_default_manifest_detects_poetry_dependency_group_pytest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_mixed.py").write_text(
                "import unittest\n\n"
                "class PassingTest(unittest.TestCase):\n"
                "    def test_passing(self):\n"
                "        self.assertTrue(True)\n\n"
                "def test_pytest_failure():\n"
                "    assert False\n"
            )
            (root / "pyproject.toml").write_text(
                "[tool.poetry]\n"
                "name='poetry-project'\n"
                "version='0.1.0'\n\n"
                "[tool.poetry.group.dev.dependencies]\n"
                "pytest='^8.0'\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [{"name": "python-pytest", "run": ["python3", "-m", "pytest"]}],
        )

    def test_default_manifest_schedules_root_level_unittest_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_failure.py").write_text(
                "import unittest\n\n"
                "class FailureTest(unittest.TestCase):\n"
                "    def test_failure(self):\n"
                "        self.fail('expected')\n"
            )
            (root / "pyproject.toml").write_text(
                "[project]\nname='unittest-project'\nversion='0.1.0'\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-unittest",
                    "run": ["python3", "-m", "unittest", "discover", "-s", ".", "-v"],
                }
            ],
        )

    def test_root_project_owns_nested_unittest_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[project]\nname='unittest-project'\nversion='0.1.0'\n"
            )
            package = root / "package"
            package.mkdir()
            (package / "test_nested.py").write_text(
                "import unittest\n\n"
                "class NestedTest(unittest.TestCase):\n"
                "    def test_nested(self):\n"
                "        self.assertTrue(True)\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-unittest",
                    "run": ["python3", "-m", "unittest", "discover", "-s", ".", "-v"],
                }
            ],
        )

    def test_root_project_deduplicates_nested_module_and_tests_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[project]\nname='unittest-project'\nversion='0.1.0'\n"
            )
            package = root / "package"
            tests = package / "tests"
            tests.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (tests / "__init__.py").write_text("")
            (package / "test_module.py").write_text(
                "import unittest\n\n"
                "class ModuleTest(unittest.TestCase):\n"
                "    def test_module(self):\n"
                "        self.assertTrue(True)\n"
            )
            (tests / "test_nested.py").write_text(
                "import unittest\n\n"
                "class NestedTest(unittest.TestCase):\n"
                "    def test_nested(self):\n"
                "        self.assertTrue(True)\n"
            )
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-unittest",
                    "run": ["python3", "-m", "unittest", "discover", "-s", ".", "-v"],
                }
            ],
        )

    def test_parent_pytest_ignores_nested_pytest_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                "[project]\n"
                "name='parent'\n"
                "version='0.1.0'\n"
                "dependencies=['pytest']\n"
            )
            (root / "tests").mkdir()
            (root / "tests" / "test_parent.py").write_text("def test_parent():\n    assert True\n")
            child = root / "package"
            (child / "tests").mkdir(parents=True)
            (child / "pyproject.toml").write_text(
                "[project]\n"
                "name='child'\n"
                "version='0.1.0'\n"
                "dependencies=['pytest']\n"
            )
            (child / "tests" / "test_child.py").write_text("def test_child():\n    assert True\n")
            data = strict_gate.discover_default_manifest(root)
        python_commands = [
            command
            for command in data["components"][0]["commands"]
            if command["name"].startswith("python-")
        ]
        self.assertEqual(
            python_commands,
            [
                {
                    "name": "python-pytest",
                    "run": ["python3", "-m", "pytest", "--ignore=package"],
                },
                {
                    "name": "python-pytest-package",
                    "run": ["python3", "-m", "pytest"],
                    "cwd": "package",
                },
            ],
        )

    def test_default_manifest_discovers_independent_cargo_and_go_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ("cargo-one/Cargo.toml", "cargo-two/Cargo.toml"):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_text("[package]\nname='x'\nversion='0.1.0'\n")
            workspace = root / "cargo-workspace"
            (workspace / "member").mkdir(parents=True)
            (workspace / "Cargo.toml").write_text("[workspace]\nmembers=['member']\n")
            (workspace / "member" / "Cargo.toml").write_text("[package]\nname='member'\nversion='0.1.0'\n")
            for relative in ("go-one/go.mod", "go-two/go.mod"):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_text("module example.invalid/test\n")
            data = strict_gate.discover_default_manifest(root)
        commands = data["components"][0]["commands"]
        cargo_test_cwds = {command["cwd"] for command in commands if command["name"].startswith("cargo-test")}
        go_test_cwds = {command["cwd"] for command in commands if command["name"].startswith("go-test")}
        self.assertEqual(cargo_test_cwds, {"cargo-one", "cargo-two", "cargo-workspace"})
        self.assertEqual(go_test_cwds, {"go-one", "go-two"})

    def test_default_manifest_keeps_packages_excluded_from_ancestor_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            for relative in ("app/Cargo.toml", "tools/Cargo.toml"):
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[package]\nname='x'\nversion='0.1.0'\n")
            (workspace / "Cargo.toml").write_text(
                "[workspace]\nmembers=['app']\nexclude=['tools']\n"
            )
            data = strict_gate.discover_default_manifest(root)
        cargo_test_cwds = {
            command["cwd"]
            for command in data["components"][0]["commands"]
            if command["name"].startswith("cargo-test")
        }
        self.assertEqual(cargo_test_cwds, {"workspace", "workspace/tools"})


if __name__ == "__main__":
    unittest.main()
