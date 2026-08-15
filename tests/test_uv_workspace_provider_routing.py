from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main
from unified_project_manager.provider_registry import provider_summary
from unified_project_manager.uv_graph import execute_uv_graph, plan_uv_graphs, uv_provider_component_keys
from unified_project_manager.uv_impact import analyze_uv_impact


_LOCK = '''
version = 1

[[package]]
name = "root"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "foo", version = "1.0.0" }]

[[package]]
name = "app"
version = "0.1.0"
source = { editable = "packages/app" }
dependencies = [{ name = "bar", version = "1.0.0" }]

[[package]]
name = "sibling"
version = "0.1.0"
source = { editable = "packages/sibling" }
dependencies = [{ name = "baz", version = "1.0.0" }]

[[package]]
name = "foo"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "bar"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "baz"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
'''


class UvWorkspaceProviderRoutingTests(unittest.TestCase):
    def _project(self, path: Path, name: str, extra: str = "") -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\n{extra}', encoding="utf-8"
        )

    def _workspace(self, root: Path) -> None:
        self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
        self._project(root / "packages" / "app", "app")
        self._project(root / "packages" / "sibling", "sibling")
        (root / "uv.lock").write_text(_LOCK, encoding="utf-8")

    def test_unscoped_root_plan_owns_all_workspace_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            graph = discover(root)

            plans = plan_uv_graphs(graph)

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:python")
            self.assertIsNone(plans[0].selected_component)
            self.assertEqual(
                uv_provider_component_keys(graph, plans),
                {".:python", "packages/app:python", "packages/sibling:python"},
            )
            coverage = {item["component"]: item for item in provider_summary(graph)["coverage"]}
            self.assertTrue(coverage["packages/app:python"]["supported"])
            self.assertEqual(coverage["packages/app:python"]["provider"]["provider"], "uv-lock")

    def test_member_selector_scopes_shared_lock_impact_to_that_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            graph = discover(root)

            plan = plan_uv_graphs(graph, selector="app")[0]
            result = execute_uv_graph(plan)

            self.assertEqual(plan.component, ".:python")
            self.assertEqual(plan.selected_component, "packages/app:python")
            self.assertEqual(plan.selected_project_name, "app")
            self.assertEqual(uv_provider_component_keys(graph, [plan]), {".:python", "packages/app:python"})
            bar = analyze_uv_impact(result, "bar")
            self.assertEqual(len(bar), 1)
            self.assertEqual(bar[0].component, "packages/app:python")
            self.assertEqual(bar[0].project_paths, (("app@0.1.0", "bar@1.0.0"),))
            self.assertEqual(analyze_uv_impact(result, "foo"), [])
            self.assertEqual(analyze_uv_impact(result, "baz"), [])

    def test_public_member_impact_does_not_leak_sibling_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["impact", "bar", str(root), "--native", "--component", "app", "--json"])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(len(data["impacts"]), 1)
            self.assertEqual(data["impacts"][0]["component"], "packages/app:python")
            self.assertEqual(data["impacts"][0]["project_paths"], [["app@0.1.0", "bar@1.0.0"]])

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["impact", "foo", str(root), "--native", "--component", "app", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(data["impacts"], [])


if __name__ == "__main__":
    unittest.main()
