from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.native_graph import (
    NativeGraphResult,
    NativeModule,
    NativeRequirementEdge,
    NativeWhyResult,
)


class NativeEntrypointTests(unittest.TestCase):
    def _go_project(self, root: Path) -> None:
        (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")

    def test_native_graph_preview_exposes_readonly_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go_project(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["graph", str(root), "--native", "--preview", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["plans"][0]["selected_argv"], ["go", "list", "-mod=readonly", "-m", "-json", "all"])
            self.assertEqual(data["plans"][0]["edges_argv"], ["go", "mod", "graph"])

    def test_native_graph_json_keeps_selected_and_required_versions_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go_project(root)

            def fake_execute(plan):
                modules = [
                    NativeModule(plan.component, "example.com/app", None, main=True),
                    NativeModule(plan.component, "example.com/a", "v1.2.0"),
                    NativeModule(plan.component, "example.com/b", "v1.4.0"),
                ]
                edges = [NativeRequirementEdge(plan.component, "example.com/app", None, "example.com/b", "v1.3.0", "v1.4.0", True)]
                return NativeGraphResult(plan, modules, edges, 0)

            output = io.StringIO()
            with patch("unified_project_manager.native_entrypoint.execute_native_graph", side_effect=fake_execute), redirect_stdout(output):
                code = main(["graph", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            edge = data["results"][0]["edges"][0]
            self.assertEqual(edge["required_version"], "v1.3.0")
            self.assertEqual(edge["selected_version"], "v1.4.0")

    def test_native_why_routes_to_authoritative_module_why(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go_project(root)
            result = NativeWhyResult(".:go", "go", "example.com/a", True, ("example.com/app/pkg", "example.com/a/pkg"), 0)
            output = io.StringIO()
            with patch("unified_project_manager.native_entrypoint.query_native_why", return_value=([result], [])), redirect_stdout(output):
                code = main(["why", "example.com/a", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["results"][0]["path"], ["example.com/app/pkg", "example.com/a/pkg"])

    def test_native_sbom_adds_go_selected_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go_project(root)

            def fake_execute(plan):
                modules = [
                    NativeModule(plan.component, "example.com/app", None, main=True),
                    NativeModule(plan.component, "golang.org/x/text", "v0.22.0"),
                ]
                return NativeGraphResult(plan, modules, [], 0)

            output = io.StringIO()
            with patch("unified_project_manager.native_entrypoint.execute_native_graph", side_effect=fake_execute), redirect_stdout(output):
                code = main(["sbom", str(root), "--native"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertIn("pkg:golang/golang.org%2Fx%2Ftext@v0.22.0", {item.get("purl") for item in data["components"]})


if __name__ == "__main__":
    unittest.main()
