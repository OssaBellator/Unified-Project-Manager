from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.go_symbol_source_observation import (
    GoSymbolSourceObservationError,
    build_go_symbol_source_observation_plan,
    execute_go_symbol_source_observation,
    parse_go_symbol_build_environment,
    parse_go_symbol_package_inputs,
)


class GoSymbolSourceObservationTests(unittest.TestCase):
    def test_plan_is_offline_single_module_readonly_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build_go_symbol_source_observation_plan(root, executable="/tools/go")

            self.assertEqual(plan.cwd, root.resolve())
            self.assertEqual(plan.env_argv, ("/tools/go", "env", "-json"))
            self.assertEqual(
                plan.packages_argv,
                ("/tools/go", "list", "-mod=readonly", "-deps", "-json", "./..."),
            )
            self.assertEqual(plan.environment["GOPROXY"], "off")
            self.assertEqual(plan.environment["GOWORK"], "off")
            self.assertEqual(plan.environment["GOSUMDB"], "off")
            self.assertEqual(plan.environment["GOTOOLCHAIN"], "local")
            data = plan.to_dict()
            self.assertEqual(data["freshness"], "not-established")
            self.assertEqual(data["govulncheck_equivalence"], "not-established")
            self.assertEqual(data["project_mutation"], "none-planned")

    def test_build_environment_keeps_resolved_build_inputs_only(self) -> None:
        environment = parse_go_symbol_build_environment(json.dumps({
            "GOOS": "linux",
            "GOARCH": "amd64",
            "GOVERSION": "go1.24.0",
            "CGO_ENABLED": "1",
            "GOFLAGS": "-tags=integration",
            "GOAMD64": "v3",
            "CC": "gcc",
            "GOMODCACHE": "/ignored/path",
        }))

        self.assertEqual(environment.get("GOOS"), "linux")
        self.assertEqual(environment.get("GOARCH"), "amd64")
        self.assertEqual(environment.get("GOFLAGS"), "-tags=integration")
        self.assertEqual(environment.get("GOAMD64"), "v3")
        self.assertIsNone(environment.get("GOMODCACHE"))
        self.assertEqual(
            environment.to_dict()["GOVERSION"],
            "go1.24.0",
        )

    def test_build_environment_requires_goos_goarch_and_goversion(self) -> None:
        for value, missing in (
            ({"GOARCH": "amd64", "GOVERSION": "go1.24.0"}, "GOOS"),
            ({"GOOS": "linux", "GOVERSION": "go1.24.0"}, "GOARCH"),
            ({"GOOS": "linux", "GOARCH": "amd64"}, "GOVERSION"),
        ):
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(GoSymbolSourceObservationError, missing):
                    parse_go_symbol_build_environment(json.dumps(value))

    def test_package_parser_preserves_selected_ignored_module_and_import_inputs(self) -> None:
        stream = "\n".join([
            json.dumps({
                "Dir": "/tmp/dep/pkg",
                "ImportPath": "example.com/dep/pkg",
                "Name": "pkg",
                "DepOnly": True,
                "Module": {
                    "Path": "example.com/dep",
                    "Version": "v1.2.3",
                },
                "GoFiles": ["dep_linux.go", "dep.go"],
                "CgoFiles": ["cgo.go"],
                "HFiles": ["dep.h"],
                "IgnoredGoFiles": ["dep_windows.go"],
                "EmbedFiles": ["asset.txt"],
                "Imports": ["unsafe", "fmt", "fmt"],
            }),
            json.dumps({
                "Dir": "/tmp/app",
                "ImportPath": "example.com/app",
                "Name": "main",
                "Module": {
                    "Path": "example.com/app",
                    "Main": True,
                },
                "GoFiles": ["main.go"],
                "Imports": ["example.com/dep/pkg"],
            }),
        ])

        packages = parse_go_symbol_package_inputs(stream)
        self.assertEqual([package.import_path for package in packages], ["example.com/app", "example.com/dep/pkg"])
        app, dep = packages
        self.assertFalse(app.dep_only)
        self.assertTrue(app.module.main)
        self.assertEqual(app.selected_files, ("main.go",))
        self.assertTrue(dep.dep_only)
        self.assertEqual(dep.module.path, "example.com/dep")
        self.assertEqual(dep.module.version, "v1.2.3")
        self.assertFalse(dep.module.replaced)
        self.assertEqual(
            dep.selected_files,
            ("asset.txt", "cgo.go", "dep.go", "dep.h", "dep_linux.go"),
        )
        data = dep.to_dict()
        self.assertEqual(data["ignored_files"]["IgnoredGoFiles"], ["dep_windows.go"])
        self.assertEqual(data["imports"], ["fmt", "unsafe"])

    def test_package_parser_retains_replacement_identity_and_rejects_incomplete_records(self) -> None:
        replacement = json.dumps({
            "Dir": "/tmp/fork/pkg",
            "ImportPath": "example.com/original/pkg",
            "Module": {
                "Path": "example.com/original",
                "Version": "v1.2.3",
                "Replace": {
                    "Path": "example.com/fork",
                    "Version": "v1.2.3-fixed",
                },
            },
            "GoFiles": ["dep.go"],
        })
        package = parse_go_symbol_package_inputs(replacement)[0]
        self.assertTrue(package.module.replaced)
        self.assertEqual(package.module.effective_path, "example.com/fork")
        self.assertEqual(package.module.effective_version, "v1.2.3-fixed")

        for record, reason in (
            ({"ImportPath": "x", "Dir": "/tmp/x", "Incomplete": True}, "incomplete"),
            ({"ImportPath": "x", "Dir": "/tmp/x", "Error": {"Err": "bad"}}, "Error record"),
            ({"ImportPath": "x", "Dir": "/tmp/x", "DepsErrors": [{"Err": "bad"}]}, "dependency errors"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(GoSymbolSourceObservationError, reason):
                    parse_go_symbol_package_inputs(json.dumps(record))

    def test_execution_uses_resolved_go_and_same_guards_for_env_and_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build_go_symbol_source_observation_plan(root)
            calls = []

            env_payload = json.dumps({
                "GOOS": "linux",
                "GOARCH": "amd64",
                "GOVERSION": "go1.24.0",
                "CGO_ENABLED": "0",
                "GOFLAGS": "",
            })
            package_payload = json.dumps({
                "Dir": str(root),
                "ImportPath": "example.com/app",
                "Name": "main",
                "Module": {"Path": "example.com/app", "Main": True},
                "GoFiles": ["main.go"],
            })

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                if argv[1:3] == ["env", "-json"]:
                    return subprocess.CompletedProcess(argv, 0, env_payload, "")
                return subprocess.CompletedProcess(argv, 0, package_payload, "")

            old = os.environ.get("UPM_SOURCE_OBSERVATION_SENTINEL")
            os.environ["UPM_SOURCE_OBSERVATION_SENTINEL"] = "present"
            try:
                result = execute_go_symbol_source_observation(
                    plan,
                    run=run,
                    which=lambda _name: "/tools/go",
                )
            finally:
                if old is None:
                    os.environ.pop("UPM_SOURCE_OBSERVATION_SENTINEL", None)
                else:
                    os.environ["UPM_SOURCE_OBSERVATION_SENTINEL"] = old

            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(len(calls), 2)
            for argv, kwargs in calls:
                self.assertEqual(argv[0], "/tools/go")
                self.assertEqual(kwargs["cwd"], root.resolve())
                self.assertEqual(kwargs["env"]["GOPROXY"], "off")
                self.assertEqual(kwargs["env"]["GOWORK"], "off")
                self.assertEqual(kwargs["env"]["GOSUMDB"], "off")
                self.assertEqual(kwargs["env"]["GOTOOLCHAIN"], "local")
                self.assertEqual(kwargs["env"]["UPM_SOURCE_OBSERVATION_SENTINEL"], "present")
            self.assertEqual(result.observation.root_packages, ("example.com/app",))
            self.assertFalse(result.to_dict()["persisted"])

    def test_execution_failure_and_parse_failure_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build_go_symbol_source_observation_plan(root)

            missing = execute_go_symbol_source_observation(plan, which=lambda _name: None)
            self.assertFalse(missing.succeeded)
            self.assertEqual(missing.returncode, 127)

            env_failure = execute_go_symbol_source_observation(
                plan,
                which=lambda _name: "/tools/go",
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 2, "", "env failed"),
            )
            self.assertFalse(env_failure.succeeded)
            self.assertEqual(env_failure.returncode, 2)
            self.assertIn("go env", env_failure.error or "")

            calls = 0

            def invalid_packages(argv, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return subprocess.CompletedProcess(
                        argv, 0,
                        json.dumps({"GOOS": "linux", "GOARCH": "amd64", "GOVERSION": "go1.24.0"}),
                        "",
                    )
                return subprocess.CompletedProcess(argv, 0, "not-json", "")

            invalid = execute_go_symbol_source_observation(
                plan,
                which=lambda _name: "/tools/go",
                run=invalid_packages,
            )
            self.assertFalse(invalid.succeeded)
            self.assertIn("Could not parse `go list -json`", invalid.error or "")


if __name__ == "__main__":
    unittest.main()
