from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.native_graph import NativeGraphPlan, NativeGraphResult, NativeModule, NativeRequirementEdge
from unified_project_manager.native_impact import analyze_native_impact


def _result(root: Path) -> NativeGraphResult:
    plan = NativeGraphPlan(".:go", "go", "go", root, ("go",), ("go",))
    modules = [
        NativeModule(".:go", "example.com/app", None, main=True),
        NativeModule(".:go", "example.com/a", "v1.2.0"),
        NativeModule(".:go", "example.com/b", "v1.4.0"),
        NativeModule(".:go", "example.com/old", "v1.0.0", replacement_name="example.com/new", replacement_version="v1.1.0"),
    ]
    edges = [
        NativeRequirementEdge(".:go", "example.com/app", None, "example.com/a", "v1.2.0", "v1.2.0", True),
        NativeRequirementEdge(".:go", "example.com/a", "v1.2.0", "example.com/b", "v1.4.0", "v1.4.0", True),
        NativeRequirementEdge(".:go", "example.com/a", "v1.1.0", "example.com/b", "v1.2.0", "v1.4.0", False),
    ]
    return NativeGraphResult(plan, modules, edges, 0)


class NativeImpactTests(unittest.TestCase):
    def test_reverse_impact_uses_only_selected_source_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            impact = analyze_native_impact(_result(Path(temporary)), "example.com/b")[0]
            self.assertEqual(impact.selected_version, "v1.4.0")
            self.assertEqual(impact.direct_dependents, ("example.com/a",))
            self.assertEqual(impact.transitive_dependents, ("example.com/a",))
            self.assertIn(("example.com/app", "example.com/a", "example.com/b"), impact.root_paths)

    def test_effective_replacement_name_can_be_queried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            impact = analyze_native_impact(_result(Path(temporary)), "example.com/new")[0]
            self.assertEqual(impact.module, "example.com/old")
            self.assertEqual(impact.effective_name, "example.com/new")
            self.assertEqual(impact.selected_version, "v1.1.0")

    def test_public_impact_json_labels_provider_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            result = _result(root)
            output = io.StringIO()
            with patch("unified_project_manager.impact_provider_entrypoint.execute_native_graph", return_value=result), redirect_stdout(output):
                code = main(["impact", "example.com/b", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["impacts"][0]["provider"], "go-modules")
            self.assertEqual(data["impacts"][0]["scope"], "module-requirement")
            self.assertEqual(data["impacts"][0]["direct_dependents"], ["example.com/a"])
            self.assertIn(["example.com/app", "example.com/a", "example.com/b"], data["impacts"][0]["root_paths"])

    def test_fleet_impact_json_correlates_registered_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects = []
            for name in ("one", "two"):
                project = root / name
                project.mkdir()
                (project / "go.mod").write_text(f"module example.com/{name}\ngo 1.24\n", encoding="utf-8")
                projects.append(project)
            registry = root / "projects.json"
            registry.write_text(json.dumps({"version": 1, "projects": [str(project) for project in projects]}), encoding="utf-8")

            def fake_execute(plan):
                project_name = plan.cwd.name
                result = _result(plan.cwd)
                result.plan = NativeGraphPlan(".:go", "go", "go", plan.cwd, ("go",), ("go",))
                result.modules[0] = NativeModule(".:go", f"example.com/{project_name}", None, main=True)
                result.edges[0] = NativeRequirementEdge(".:go", f"example.com/{project_name}", None, "example.com/a", "v1.2.0", "v1.2.0", True)
                return result

            output = io.StringIO()
            with patch("unified_project_manager.impact_entrypoint.execute_native_graph", side_effect=fake_execute), redirect_stdout(output):
                code = main(["projects", "impact", "example.com/b", "--native", "--registry", str(registry), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["scope"], "module-requirement")
            self.assertEqual(data["affected_projects"], 2)
            self.assertEqual(len(data["impacts"]), 2)


if __name__ == "__main__":
    unittest.main()
