from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import tempfile
import tomllib
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from unified_project_manager import __version__
import unified_project_manager.package_contract as package_contract_module
import unified_project_manager.package_planner as package_planner_module
from unified_project_manager.discovery import discover
from unified_project_manager.models import CommandPlan, Component, ProjectGraph
from unified_project_manager.package_contract import (
    CONTRACT_VERSION,
    EXECUTION_SCHEMA_VERSION,
    PROVIDER_VERSION,
    PackageContractError,
    error_response,
    plan_package_operation,
    plan_package_operation_json,
)
from unified_project_manager.root_entrypoint import main as root_main


class PackageContractTests(unittest.TestCase):
    def test_provider_version_matches_package_release_metadata(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(PROVIDER_VERSION, __version__)
        self.assertEqual(PROVIDER_VERSION, project["project"]["version"])

    def _node(self, root: Path, manager: str, lockfile: str, *, version: str = "10.0.0") -> None:
        (root / "package.json").write_text(
            json.dumps({"name": "fixture", "packageManager": f"{manager}@{version}"}),
            encoding="utf-8",
        )
        (root / lockfile).write_text("{}" if lockfile.endswith(".json") else "", encoding="utf-8")

    def _python(self, root: Path, manager: str) -> None:
        if manager == "pip":
            (root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
            return
        sections = {
            "uv": "[project]\nname='fixture'\n[tool.uv]\n",
            "poetry": "[tool.poetry]\nname='fixture'\nversion='0.1.0'\n",
            "pdm": "[project]\nname='fixture'\n[tool.pdm]\n",
        }
        locks = {"uv": "uv.lock", "poetry": "poetry.lock", "pdm": "pdm.lock"}
        (root / "pyproject.toml").write_text(sections[manager], encoding="utf-8")
        (root / locks[manager]).write_text("", encoding="utf-8")

    def _rust(self, root: Path) -> None:
        (root / "Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.1.0'\n", encoding="utf-8")
        (root / "Cargo.lock").write_text("", encoding="utf-8")

    def _go(self, root: Path) -> None:
        (root / "go.mod").write_text("module example.com/fixture\ngo 1.24\n", encoding="utf-8")
        (root / "go.sum").write_text("", encoding="utf-8")

    def _dotnet(self, root: Path, *, project_name: str = "Fixture.csproj", locked: bool = True) -> None:
        (root / project_name).write_text(
            "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
            "  <PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>\n"
            "  <ItemGroup><PackageReference Include=\"Microsoft.Extensions.Logging\" Version=\"10.0.0\" /></ItemGroup>\n"
            "</Project>\n",
            encoding="utf-8",
        )
        if locked:
            (root / "packages.lock.json").write_text('{"version":1,"dependencies":{}}', encoding="utf-8")

    def test_representative_execution_contracts(self) -> None:
        cases = [
            ("npm", "node", "install", (), False, ("npm", "install")),
            ("npm", "node", "sync", (), False, ("npm", "ci")),
            ("npm", "node", "add", ("react@19",), True, ("npm", "install", "--save-dev", "react@19")),
            ("npm", "node", "remove", ("react",), False, ("npm", "uninstall", "react")),
            ("pnpm", "node", "install", (), False, ("pnpm", "install")),
            ("pnpm", "node", "sync", (), False, ("pnpm", "install", "--frozen-lockfile")),
            ("pnpm", "node", "add", ("react",), True, ("pnpm", "add", "--save-dev", "react")),
            ("pnpm", "node", "remove", ("react",), False, ("pnpm", "remove", "react")),
            ("yarn", "node", "install", (), False, ("yarn", "install")),
            ("yarn", "node", "sync", (), False, ("yarn", "install", "--immutable")),
            ("yarn", "node", "add", ("react",), True, ("yarn", "add", "--dev", "react")),
            ("yarn", "node", "remove", ("react",), False, ("yarn", "remove", "react")),
            ("bun", "node", "install", (), False, ("bun", "install")),
            ("bun", "node", "sync", (), False, ("bun", "install", "--frozen-lockfile")),
            ("bun", "node", "add", ("zod",), True, ("bun", "add", "--dev", "zod")),
            ("bun", "node", "remove", ("zod",), False, ("bun", "remove", "zod")),
            ("uv", "python", "install", (), False, ("uv", "sync")),
            ("uv", "python", "sync", (), False, ("uv", "sync", "--locked")),
            ("uv", "python", "add", ("pytest",), True, ("uv", "add", "--dev", "pytest")),
            ("uv", "python", "remove", ("pytest",), False, ("uv", "remove", "pytest")),
            ("poetry", "python", "install", (), False, ("poetry", "install")),
            ("poetry", "python", "sync", (), False, ("poetry", "sync")),
            ("poetry", "python", "add", ("pytest",), True, ("poetry", "add", "--group", "dev", "pytest")),
            ("poetry", "python", "remove", ("pytest",), False, ("poetry", "remove", "pytest")),
            ("pdm", "python", "install", (), False, ("pdm", "install")),
            ("pdm", "python", "sync", (), False, ("pdm", "sync")),
            ("pdm", "python", "add", ("pytest",), True, ("pdm", "add", "--dev", "pytest")),
            ("pdm", "python", "remove", ("requests",), False, ("pdm", "remove", "requests")),
            ("pip", "python", "install", (), False, ("python", "-m", "pip", "install", "-r", "requirements.txt")),
            ("cargo", "rust", "install", (), False, ("cargo", "fetch")),
            ("cargo", "rust", "sync", (), False, ("cargo", "fetch", "--locked")),
            ("cargo", "rust", "add", ("serde",), True, ("cargo", "add", "--dev", "serde")),
            ("cargo", "rust", "remove", ("serde",), False, ("cargo", "remove", "serde")),
            ("go", "go", "install", (), False, ("go", "mod", "download")),
            ("go", "go", "sync", (), False, ("go", "mod", "download")),
            ("go", "go", "add", ("example.com/dep@v1.2.3",), False, ("go", "get", "example.com/dep@v1.2.3")),
            ("go", "go", "remove", ("example.com/dep",), False, ("go", "get", "example.com/dep@none")),
            ("nuget", "dotnet", "install", (), False, ("dotnet", "restore", "Fixture.csproj")),
            ("nuget", "dotnet", "sync", (), False, ("dotnet", "restore", "Fixture.csproj", "--locked-mode")),
            ("nuget", "dotnet", "add", ("Newtonsoft.Json@13.0.3",), False, ("dotnet", "package", "add", "Newtonsoft.Json", "--version", "13.0.3", "--project", "Fixture.csproj")),
            ("nuget", "dotnet", "remove", ("Newtonsoft.Json",), False, ("dotnet", "package", "remove", "Newtonsoft.Json", "--project", "Fixture.csproj")),
        ]
        node_locks = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock", "bun": "bun.lock"}
        for manager, ecosystem, operation, packages, dev, argv in cases:
            with self.subTest(manager=manager), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                if ecosystem == "node":
                    self._node(root, manager, node_locks[manager], version="4.9.2" if manager == "yarn" else "10.0.0")
                elif ecosystem == "python":
                    self._python(root, manager)
                elif ecosystem == "rust":
                    self._rust(root)
                elif ecosystem == "go":
                    self._go(root)
                else:
                    self._dotnet(root)

                result = plan_package_operation(root, operation, packages=packages, dev=dev).to_dict()
                self.assertEqual(result["schemaVersion"], 2)
                self.assertIs(result["ok"], True)
                self.assertEqual(result["provider"]["version"], PROVIDER_VERSION)
                self.assertEqual(PROVIDER_VERSION, __version__)
                self.assertEqual(result["contract"]["version"], CONTRACT_VERSION)
                self.assertEqual(result["compatibility"]["executionSchemaVersions"], [2])
                self.assertEqual(result["compatibility"]["executionConstraintKinds"], ["environment", "filesystem", "network", "prerequisites", "sources"])
                self.assertNotIn("executionConstraints", result)
                execution = result["execution"]
                self.assertEqual(
                    set(execution),
                    {"schemaVersion", "operation", "component", "ecosystem", "manager", "cwd", "packages", "dev", "argv", "mutationScope", "networkRequired", "executionConstraints"},
                )
                self.assertEqual(execution["schemaVersion"], EXECUTION_SCHEMA_VERSION)
                self.assertEqual(EXECUTION_SCHEMA_VERSION, 2)
                self.assertEqual(execution["operation"], operation)
                self.assertEqual(execution["component"], f".:{ecosystem}")
                self.assertEqual(execution["ecosystem"], ecosystem)
                self.assertEqual(execution["manager"], manager)
                self.assertEqual(execution["cwd"], ".")
                self.assertEqual(execution["packages"], list(packages))
                self.assertEqual(execution["dev"], dev)
                self.assertEqual(execution["argv"], list(argv))
                self.assertEqual(execution["mutationScope"], {"workspace": True, "external": False})
                self.assertIs(execution["networkRequired"], True)
                constraints = execution["executionConstraints"]
                expected_environment = {"GOWORK": "off"} if manager == "go" else {}
                self.assertEqual(constraints["environment"], expected_environment)
                self.assertEqual(constraints["filesystem"], {
                    "projectWrites": "workspace-only",
                    "externalProjectWrites": False,
                    "packageCache": "executor-isolated",
                    "ambientProjectConfiguration": "isolated",
                })
                self.assertEqual(constraints["network"], {"required": True, "egress": "allowlisted"})
                expected_executable = "python" if manager == "pip" else "dotnet" if manager == "nuget" else manager
                self.assertEqual(constraints["prerequisites"]["executables"], [expected_executable])
                self.assertIs(constraints["prerequisites"]["provisioningAllowed"], False)
                self.assertEqual(constraints["prerequisites"]["minimumVersions"], {"dotnet": "10.0.0"} if manager == "nuget" else {})
                self.assertEqual(constraints["sources"]["policy"], "consumer-approved-registry-only")
                self.assertIs(constraints["sources"]["allowCallerOverrides"], False)
                self.assertIs(constraints["sources"]["allowProjectOverrides"], False)
                self.assertIs(constraints["sources"]["allowAmbientOverrides"], False)
                self.assertIs(constraints["sources"]["allowLocalPaths"], False)
                self.assertIs(constraints["sources"]["allowUrls"], False)
                self.assertIs(constraints["sources"]["allowVcs"], False)

    def test_nested_component_cwd_is_project_relative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "apps" / "web"
            nested.mkdir(parents=True)
            self._node(nested, "npm", "package-lock.json")
            plan = plan_package_operation(root, "sync", component="apps/web")
            result = plan.execution_dict()
            self.assertEqual(result["component"], "apps/web:node")
            self.assertEqual(result["cwd"], "apps/web")
            self.assertEqual(plan.workspace_scope.to_dict(), {"kind": "standalone", "rootComponent": None, "memberComponents": [], "issueCodes": []})

    def test_static_workspace_roots_are_explicit_and_members_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (root / "package.json").write_text(json.dumps({
                "name": "root",
                "private": True,
                "packageManager": "npm@10.0.0",
                "workspaces": ["packages/*"],
            }), encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            root_plan = plan_package_operation(root, "sync", component=".:node").to_dict()
            self.assertEqual(root_plan["workspaceScope"]["kind"], "workspace_root")
            self.assertEqual(root_plan["workspaceScope"]["rootComponent"], ".:node")
            self.assertEqual(root_plan["workspaceScope"]["memberComponents"], ["packages/app:node"])
            with self.assertRaises(PackageContractError) as member_error:
                plan_package_operation(root, "install", component="packages/app:node")
            self.assertEqual(member_error.exception.code, "workspace_member_requires_owner")
            self.assertEqual(member_error.exception.details["workspaceRootComponent"], ".:node")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "crates" / "core"
            member.mkdir(parents=True)
            (root / "Cargo.toml").write_text('[workspace]\nmembers=["crates/*"]\n[package]\nname="root"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("", encoding="utf-8")
            (member / "Cargo.toml").write_text('[package]\nname="core"\nversion="0.1.0"\n', encoding="utf-8")
            root_plan = plan_package_operation(root, "sync", component=".:rust").to_dict()
            self.assertEqual(root_plan["workspaceScope"]["kind"], "workspace_root")
            self.assertIn("crates/core:rust", root_plan["workspaceScope"]["memberComponents"])
            with self.assertRaises(PackageContractError) as member_error:
                plan_package_operation(root, "install", component="crates/core:rust")
            self.assertEqual(member_error.exception.code, "workspace_member_requires_owner")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "packages" / "lib"
            member.mkdir(parents=True)
            (root / "pyproject.toml").write_text('[project]\nname="root"\n[tool.uv.workspace]\nmembers=["packages/*"]\n', encoding="utf-8")
            (root / "uv.lock").write_text("", encoding="utf-8")
            (member / "pyproject.toml").write_text('[project]\nname="lib"\n', encoding="utf-8")
            root_plan = plan_package_operation(root, "sync", component=".:python").to_dict()
            self.assertEqual(root_plan["workspaceScope"]["kind"], "workspace_root")
            self.assertIn("packages/lib:python", root_plan["workspaceScope"]["memberComponents"])
            with self.assertRaises(PackageContractError) as member_error:
                plan_package_operation(root, "install", component="packages/lib:python")
            self.assertEqual(member_error.exception.code, "workspace_member_requires_owner")

    def test_pnpm_workspace_requires_native_ownership_inspection_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (root / "package.json").write_text(json.dumps({"name": "root", "private": True, "packageManager": "pnpm@10.0.0"}), encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            with mock.patch.object(subprocess, "run", side_effect=AssertionError("pnpm inspection execution forbidden")):
                with self.assertRaises(PackageContractError) as caught:
                    plan_package_operation(root, "install", component=".:node")
            self.assertEqual(caught.exception.code, "workspace_inspection_required")
            self.assertEqual(caught.exception.details["workspaceRoot"], ".")

    def test_json_request_entrypoint_is_versioned_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._rust(root)
            response = plan_package_operation_json({
                "requestSchemaVersion": 1,
                "projectRoot": str(root),
                "operation": "install",
                "packages": [],
                "dev": False,
            })
            self.assertEqual(response["execution"]["argv"], ["cargo", "fetch"])
            with self.assertRaisesRegex(PackageContractError, "unknown request fields"):
                plan_package_operation_json({
                    "requestSchemaVersion": 1,
                    "projectRoot": str(root),
                    "operation": "install",
                    "unexpected": True,
                })
            with self.assertRaises(PackageContractError) as incompatible:
                plan_package_operation_json({
                    "requestSchemaVersion": True,
                    "projectRoot": str(root),
                    "operation": "install",
                })
            self.assertEqual(incompatible.exception.code, "incompatible_request_schema")

    def test_cli_json_entrypoint_emits_only_the_provider_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node(root, "npm", "package-lock.json")
            output = io.StringIO()
            with redirect_stdout(output):
                code = root_main(["package-plan", "sync", "--root", str(root), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["schemaVersion"], 2)
            self.assertIs(payload["ok"], True)
            self.assertEqual(payload["execution"]["argv"], ["npm", "ci"])
            self.assertEqual(payload["compatibility"]["planningEffects"]["networkAccess"], False)

    def test_ambiguous_component_selection_fails_closed_with_bounded_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / "one"
            two = root / "two"
            one.mkdir()
            two.mkdir()
            self._node(one, "npm", "package-lock.json")
            self._rust(two)
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "component_ambiguous")
            self.assertLessEqual(len(caught.exception.message), 512)
            envelope = error_response(caught.exception)
            self.assertEqual(envelope["schemaVersion"], 2)
            self.assertIs(envelope["ok"], False)
            self.assertNotIn("execution", envelope)
            self.assertEqual(envelope["error"]["details"]["components"], ["one:node", "two:rust"])

    def test_lock_and_manager_conflicts_have_stable_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"fixture","packageManager":"npm@10.0.0"}', encoding="utf-8")
            with self.assertRaises(PackageContractError) as missing_lock:
                plan_package_operation(root, "sync")
            self.assertEqual(missing_lock.exception.code, "lock_required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"fixture","packageManager":"npm@10.0.0"}', encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            with self.assertRaises(PackageContractError) as conflict:
                plan_package_operation(root, "install")
            self.assertEqual(conflict.exception.code, "manager_conflict")

    def test_external_working_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as project_temporary, tempfile.TemporaryDirectory() as external_temporary:
            root = Path(project_temporary)
            external = Path(external_temporary)
            component = Component(ecosystem="node", path=root, manager="npm", manifests=["package.json"], lockfiles=["package-lock.json"])
            graph = ProjectGraph(root=root, components=[component])
            command_plan = CommandPlan(
                operation="install",
                component=".:node",
                manager="npm",
                argv=("npm", "install"),
                cwd=external,
            )
            with mock.patch("unified_project_manager.package_contract.discover", return_value=graph), mock.patch(
                "unified_project_manager.package_contract.plan_operation", return_value=command_plan
            ):
                with self.assertRaises(PackageContractError) as caught:
                    plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "external_mutation_scope")

    def test_nonportable_package_specs_cannot_change_manager_scope_or_source(self) -> None:
        rejected = (
            "--global",
            "bad\npkg",
            "../local-package",
            "C:\\tmp\\local-package",
            "https://example.invalid/package.tgz",
            "git+https://example.invalid/repository.git",
            "github:owner/repository",
            "alias@npm:react@19",
            "react@file:../local-package",
            "name with space",
            "custom:source",
            "owner/repository",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node(root, "npm", "package-lock.json")
            for package in rejected:
                with self.subTest(package=package), self.assertRaises(PackageContractError) as caught:
                    plan_package_operation(root, "add", packages=(package,))
                self.assertEqual(caught.exception.code, "invalid_package")

    def test_yarn_sync_requires_a_declared_major_and_preserves_classic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node(root, "yarn", "yarn.lock", version="1.22.22")
            self.assertEqual(plan_package_operation(root, "sync").argv, ("yarn", "install", "--frozen-lockfile"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "sync")
            self.assertEqual(caught.exception.code, "operation_not_safe")

    def test_go_module_path_remains_a_portable_package_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go(root)
            result = plan_package_operation(root, "add", packages=("example.com/dep@v1.2.3",))
            self.assertEqual(result.argv, ("go", "get", "example.com/dep@v1.2.3"))
            constraints = result.execution_constraints_dict()
            self.assertEqual(constraints["environment"], {"GOWORK": "off"})
            self.assertEqual(constraints["network"], {"required": True, "egress": "allowlisted"})
            self.assertIs(constraints["prerequisites"]["provisioningAllowed"], False)

    def test_go_scope_changing_targets_and_dev_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go(root)
            for operation, packages, dev in (
                ("remove", ("example.com/dep@v1.2.3",), False),
                ("add", ("example.com/dep@none",), False),
                ("add", ("example.com/dep",), True),
            ):
                with self.subTest(operation=operation, packages=packages, dev=dev), self.assertRaises(PackageContractError):
                    plan_package_operation(root, operation, packages=packages, dev=dev)

    def test_pip_v1_is_install_only_and_rejects_source_directives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._python(root, "pip")
            for operation, packages in (("sync", ()), ("add", ("flask",)), ("remove", ("requests",))):
                with self.subTest(operation=operation), self.assertRaises(PackageContractError) as caught:
                    plan_package_operation(root, operation, packages=packages)
                self.assertEqual(caught.exception.code, "operation_not_safe")

        for content in (
            "-r ../outside.txt\n",
            "requests @ https://example.invalid/requests.whl\n",
            "../local-package\n",
            "git+https://example.invalid/repository.git\n",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "requirements.txt").write_text(content, encoding="utf-8")
                with self.assertRaises(PackageContractError) as caught:
                    plan_package_operation(root, "install")
                self.assertEqual(caught.exception.code, "operation_not_safe")

    def test_dotnet_project_and_solution_discovery_and_restore_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "src" / "App"
            project.mkdir(parents=True)
            self._dotnet(project)
            (root / "App.sln").write_text(
                "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "App", "src\\App\\Fixture.csproj", "{11111111-1111-1111-1111-111111111111}"\n'
                "EndProject\n",
                encoding="utf-8",
            )
            graph = discover(root)
            self.assertEqual([component.key(root) for component in graph.components], [".:dotnet", "src/App:dotnet"])
            self.assertEqual([workspace.key(root) for workspace in graph.workspaces], [".:dotnet-workspace"])
            solution = plan_package_operation(root, "install", component=".:dotnet")
            self.assertEqual(solution.argv, ("dotnet", "restore", "App.sln"))
            self.assertEqual(solution.execution_constraints_dict()["prerequisites"], {
                "executables": ["dotnet"],
                "minimumVersions": {"dotnet": "10.0.0"},
                "provisioningAllowed": False,
            })
            project_plan = plan_package_operation(root, "sync", component="src/App:dotnet")
            self.assertEqual(project_plan.argv, ("dotnet", "restore", "Fixture.csproj", "--locked-mode"))

    def test_dotnet_nuget_package_and_ambiguity_guards_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root)
            with self.assertRaisesRegex(package_planner_module.OperationError, "provider-only"):
                package_planner_module.plan_operation(discover(root), "install")
            self.assertEqual(plan_package_operation(root, "install").argv, ("dotnet", "restore", "Fixture.csproj"))
            rejected = (
                ("add", ("Newtonsoft.Json",), False, "invalid_package"),
                ("add", ("Newtonsoft.Json@13.0.3 --source",), False, "invalid_package"),
                ("add", ("../Newtonsoft.Json@13.0.3",), False, "invalid_package"),
                ("add", ("Newtonsoft.Json@https://example.invalid/pkg",), False, "invalid_package"),
                ("add", ("Newtonsoft.Json@13.0.3", "Serilog@4.0.0"), False, "invalid_packages"),
                ("add", ("Newtonsoft.Json@13.0.3",), True, "dev_unsupported"),
                ("remove", ("Newtonsoft.Json@13.0.3",), False, "invalid_package"),
            )
            for operation, packages, dev, code in rejected:
                with self.subTest(operation=operation, packages=packages, dev=dev), self.assertRaises(PackageContractError) as caught:
                    plan_package_operation(root, operation, packages=packages, dev=dev)
                self.assertEqual(caught.exception.code, code)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root, project_name="One.csproj")
            (root / "Two.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "component_ambiguous")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root, locked=False)
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "sync")
            self.assertEqual(caught.exception.code, "lock_required")

    def test_dotnet_source_and_path_smuggling_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root)
            (root / "NuGet.Config").write_text('<configuration><packageSources /></configuration>', encoding="utf-8")
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "operation_not_safe")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root)
            (root / "Directory.Build.props").write_text(
                '<Project><PropertyGroup><RestoreSources>https://example.invalid/v3/index.json</RestoreSources></PropertyGroup></Project>',
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "operation_not_safe")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Fixture.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><Import Project="..\\outside.props" /></Project>',
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "operation_not_safe")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root)
            (root / "Directory.Build.props").write_text(
                '<Project><Import Project="custom.restore.props" /></Project>',
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "operation_not_safe")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Fixture.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><RestoreOutputPath>..\\outside</RestoreOutputPath></PropertyGroup></Project>',
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "operation_not_safe")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Fixture.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><Target Name="BeforeRestore" BeforeTargets="Restore" /></Project>',
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "operation_not_safe")

        with tempfile.TemporaryDirectory() as outer:
            outer_root = Path(outer)
            root = outer_root / "project"
            outside = outer_root / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "Outside.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            (root / "Fixture.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="..\\outside\\Outside.csproj" /></ItemGroup></Project>',
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "external_mutation_scope")

        with tempfile.TemporaryDirectory() as outer:
            outer_root = Path(outer)
            root = outer_root / "project"
            outside = outer_root / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "Outside.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            (root / "App.sln").write_text(
                "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "Outside", "..\\outside\\Outside.csproj", "{11111111-1111-1111-1111-111111111111}"\n'
                "EndProject\n",
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install")
            self.assertEqual(caught.exception.code, "external_mutation_scope")

        with tempfile.TemporaryDirectory() as outer:
            outer_root = Path(outer)
            root = outer_root / "project"
            outside = outer_root / "outside"
            app = root / "src" / "App"
            app.mkdir(parents=True)
            outside.mkdir()
            (outside / "Outside.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8")
            (app / "App.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="..\\..\\..\\outside\\Outside.csproj" /></ItemGroup></Project>',
                encoding="utf-8",
            )
            (root / "App.sln").write_text(
                "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "App", "src\\App\\App.csproj", "{11111111-1111-1111-1111-111111111111}"\n'
                "EndProject\n",
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install", component=".:dotnet")
            self.assertEqual(caught.exception.code, "external_mutation_scope")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "src" / "App"
            app.mkdir(parents=True)
            (app / "App.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><RestoreSources>https://example.invalid/v3/index.json</RestoreSources></PropertyGroup></Project>',
                encoding="utf-8",
            )
            (root / "App.sln").write_text(
                "Microsoft Visual Studio Solution File, Format Version 12.00\n"
                'Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "App", "src\\App\\App.csproj", "{11111111-1111-1111-1111-111111111111}"\n'
                "EndProject\n",
                encoding="utf-8",
            )
            with self.assertRaises(PackageContractError) as caught:
                plan_package_operation(root, "install", component=".:dotnet")
            self.assertEqual(caught.exception.code, "operation_not_safe")

    def test_dotnet_planning_never_probes_or_provisions_sdk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._dotnet(root)
            with mock.patch.object(subprocess, "run", side_effect=AssertionError("dotnet execution forbidden")), mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("dotnet execution forbidden")
            ), mock.patch("shutil.which", side_effect=AssertionError("tool probing forbidden")):
                plan = plan_package_operation(root, "sync")
            self.assertEqual(plan.argv, ("dotnet", "restore", "Fixture.csproj", "--locked-mode"))
            self.assertEqual(plan.execution_constraints_dict()["prerequisites"]["executables"], ["dotnet"])
            self.assertIs(plan.execution_constraints_dict()["prerequisites"]["provisioningAllowed"], False)

    def test_dotnet_plan_is_byte_deterministic_across_absolute_roots(self) -> None:
        payloads: list[str] = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self._dotnet(root)
                payload = plan_package_operation(root, "sync").to_dict()
                payloads.append(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        self.assertEqual(payloads[0], payloads[1])
        self.assertNotIn(tempfile.gettempdir().replace("\\", "/"), payloads[0].replace("\\", "/"))

    def test_same_fixture_is_byte_deterministic_across_absolute_roots(self) -> None:
        payloads = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                nested = root / "apps" / "web"
                nested.mkdir(parents=True)
                self._node(nested, "npm", "package-lock.json")
                payload = plan_package_operation(root, "add", component="apps/web", packages=("react@19",), dev=True).to_dict()
                payloads.append(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
        self.assertEqual(payloads[0], payloads[1])

    def test_public_planner_source_is_separated_from_execution_modules(self) -> None:
        contract_source = Path(package_contract_module.__file__).read_text(encoding="utf-8")
        planner_source = Path(package_planner_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn(".operations import", contract_source)
        for forbidden in ("subprocess", "shutil.which", "socket", "receipt", "execute_plan"):
            self.assertNotIn(forbidden, planner_source)

    def test_planning_has_no_manager_network_or_project_write_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node(root, "npm", "package-lock.json")

            def snapshot() -> dict[str, tuple[bytes, int]]:
                return {
                    path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in root.rglob("*")
                    if path.is_file()
                }

            before = snapshot()
            environment_before = dict(os.environ)
            with mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess execution forbidden")), mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("subprocess execution forbidden")
            ), mock.patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), mock.patch.object(
                urllib.request, "urlopen", side_effect=AssertionError("network forbidden")
            ), mock.patch("shutil.which", side_effect=AssertionError("tool probing forbidden")), mock.patch.object(
                os, "system", side_effect=AssertionError("shell execution forbidden")
            ), mock.patch.object(Path, "write_text", side_effect=AssertionError("project write forbidden")), mock.patch.object(
                Path, "write_bytes", side_effect=AssertionError("project write forbidden")
            ), mock.patch.object(Path, "unlink", side_effect=AssertionError("project mutation forbidden")):
                result = plan_package_operation(root, "sync")
            self.assertEqual(result.argv, ("npm", "ci"))
            self.assertEqual(snapshot(), before)
            self.assertEqual(dict(os.environ), environment_before)


if __name__ == "__main__":
    unittest.main()
