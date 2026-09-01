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


if __name__ == "__main__":
    unittest.main()
