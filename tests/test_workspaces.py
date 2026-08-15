from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.discovery import discover
from unified_project_manager.doctor import diagnose
from unified_project_manager.entrypoint import main
from unified_project_manager.go_workspace import (
    execute_workspace_inspection,
    plan_workspace_inspection,
)
from unified_project_manager.native_graph import NativeGraphResult, NativeModule, NativeRequirementEdge
from unified_project_manager.state import build_state
from unified_project_manager.status import project_status
from unified_project_manager.workspace_graph import execute_workspace_graph, plan_workspace_graph


class WorkspaceTests(unittest.TestCase):
    def test_discovery_models_go_work_and_workspace_sum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "module"
            module.mkdir()
            (module / "go.mod").write_text("module example.com/module\ngo 1.24\n", encoding="utf-8")
            (root / "go.work").write_text("go 1.24\nuse ./module\n", encoding="utf-8")
            (root / "go.work.sum").write_text("example.com/a v1.0.0 h1:x\n", encoding="utf-8")

            graph = discover(root)

            self.assertEqual(len(graph.workspaces), 1)
            workspace = graph.workspaces[0]
            self.assertEqual(workspace.key(root), ".:go-workspace")
            self.assertEqual(workspace.manifests, ["go.work"])
            self.assertEqual(workspace.lockfiles, ["go.work.sum"])
            self.assertEqual(graph.to_dict()["workspaces"][0]["key"], ".:go-workspace")

    def test_workspace_only_root_is_not_reported_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.work").write_text("go 1.24\nuse ../external\n", encoding="utf-8")

            report = diagnose(discover(root), which=lambda _name: None)

            self.assertNotIn("project.empty", {finding.code for finding in report.findings})

    def test_snapshot_tracks_workspace_manifest_and_checksum_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            (root / "go.work.sum").write_text("checksum\n", encoding="utf-8")

            state = build_state(discover(root))

            self.assertEqual(state["workspaces"][0]["key"], ".:go-workspace")
            self.assertEqual(state["files"]["go.work"]["kind"], "workspace-manifest")
            self.assertEqual(state["files"]["go.work.sum"]["kind"], "workspace-state")

    def test_authoritative_inspection_maps_project_and_external_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external_temp:
            root = Path(temporary)
            member = root / "member"
            member.mkdir()
            (member / "go.mod").write_text("module example.com/member\ngo 1.24\n", encoding="utf-8")
            external = Path(external_temp)
            (external / "go.mod").write_text("module example.com/external\ngo 1.24\n", encoding="utf-8")
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            graph = discover(root)
            plan = plan_workspace_inspection(graph)
            calls: list[tuple[list[str], dict]] = []
            payload = json.dumps({
                "Go": "1.24",
                "Toolchain": "go1.24.2",
                "Use": [
                    {"DiskPath": "./member", "ModulePath": "example.com/member"},
                    {"DiskPath": str(external), "ModulePath": "example.com/external"},
                ],
                "Replace": [
                    {
                        "Old": {"Path": "example.com/old", "Version": "v1.0.0"},
                        "New": {"Path": "../fork"},
                    }
                ],
            })

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, payload, "")

            result = execute_workspace_inspection(graph, plan, run=run, which=lambda _name: "/toolchains/go")

            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0][0], "/toolchains/go")
            self.assertEqual(calls[0][1]["env"]["GOWORK"], "off")
            self.assertTrue(result.uses[0].in_project)
            self.assertEqual(result.uses[0].component, "member:go")
            self.assertFalse(result.uses[1].in_project)
            self.assertTrue(result.replacements[0].local)

    def test_nested_workspaces_require_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "nested"
            nested.mkdir()
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            (nested / "go.work").write_text("go 1.24\n", encoding="utf-8")
            graph = discover(root)

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                plan_workspace_inspection(graph)
            self.assertEqual(plan_workspace_inspection(graph, "nested").workspace, "nested:go-workspace")

    def test_workspace_graph_pins_workspace_and_readonly_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            plan = plan_workspace_graph(discover(root))
            calls: list[tuple[list[str], dict]] = []
            selected = "\n".join((
                '{"Path":"example.com/a","Main":true}',
                '{"Path":"example.com/b","Main":true}',
                '{"Path":"example.com/c","Version":"v1.2.0"}',
            ))
            edges = "example.com/a example.com/c@v1.1.0\nexample.com/b example.com/c@v1.2.0\n"

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, selected if "list" in argv else edges, "")

            result = execute_workspace_graph(plan, run=run, which=lambda _name: "/toolchains/go")

            self.assertTrue(result.succeeded)
            self.assertEqual({module.name for module in result.modules if module.main}, {"example.com/a", "example.com/b"})
            self.assertEqual(calls[0][0][0], "/toolchains/go")
            self.assertEqual(calls[0][1]["env"]["GOWORK"], str(root / "go.work"))
            self.assertIn("-mod=readonly", calls[1][1]["env"]["GOFLAGS"])
            edge = next(item for item in result.edges if item.source_name == "example.com/a")
            self.assertEqual(edge.required_version, "v1.1.0")
            self.assertEqual(edge.selected_version, "v1.2.0")

    def test_status_and_workspace_commands_expose_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")

            status = project_status(discover(root))
            self.assertEqual(status["summary"]["workspaces"], 1)
            self.assertEqual(status["workspaces"][0]["key"], ".:go-workspace")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["workspaces", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["workspaces"][0]["key"], ".:go-workspace")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["workspace", "inspect", str(root), "--preview", "--json"])
            preview = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(preview["plan"]["argv"][:4], ["go", "work", "edit", "-json"])

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["workspace", "graph", str(root), "--preview", "--json"])
            graph_preview = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(graph_preview["environment"]["GOWORK"], str(root / "go.work"))
            self.assertEqual(graph_preview["environment"]["GOFLAGS_add"], "-mod=readonly")

    def test_workspace_impact_uses_workspace_requirement_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            plan = plan_workspace_graph(discover(root))
            result = NativeGraphResult(
                plan,
                [
                    NativeModule(plan.component, "example.com/a", None, main=True),
                    NativeModule(plan.component, "example.com/b", None, main=True),
                    NativeModule(plan.component, "example.com/c", "v1.2.0"),
                ],
                [
                    NativeRequirementEdge(plan.component, "example.com/a", None, "example.com/c", "v1.1.0", "v1.2.0", True),
                    NativeRequirementEdge(plan.component, "example.com/b", None, "example.com/c", "v1.2.0", "v1.2.0", True),
                ],
                0,
            )
            output = io.StringIO()
            with patch("unified_project_manager.workspace_entrypoint.execute_workspace_graph", return_value=result), redirect_stdout(output):
                code = main(["workspace", "impact", "example.com/c", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["scope"], "workspace-module-requirement")
            paths = data["impacts"][0]["root_paths"]
            self.assertIn(["example.com/a", "example.com/c"], paths)
            self.assertIn(["example.com/b", "example.com/c"], paths)


if __name__ == "__main__":
    unittest.main()
