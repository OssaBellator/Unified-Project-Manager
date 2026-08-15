from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.pnpm_graph import (
    PnpmGraphResult,
    PnpmLogicalPackage,
    PnpmProject,
    plan_pnpm_graphs,
)
from unified_project_manager.root_entrypoint import main
from unified_project_manager.yarn_graph import (
    YarnDependencyEdge,
    YarnGraphResult,
    YarnResolvedPackage,
    plan_yarn_graphs,
)


class FleetProviderAllPublicTests(unittest.TestCase):
    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def _registry(self, path: Path, projects: list[Path]) -> Path:
        target = path / "projects.json"
        target.write_text(json.dumps({
            "version": 1,
            "projects": [str(project) for project in projects],
        }), encoding="utf-8")
        return target

    def _poetry_project(self, root: Path, dependency: str, version: str) -> None:
        (root / "pyproject.toml").write_text(f'''
[project]
name = "poetry-app"
version = "0.1.0"
dependencies = ["{dependency}"]
[tool.poetry]
name = "poetry-app"
version = "0.1.0"
''', encoding="utf-8")
        (root / "poetry.lock").write_text(f'''
[[package]]
name = "{dependency}"
version = "{version}"
[metadata]
lock-version = "2.1"
''', encoding="utf-8")

    def _pdm_project(self, root: Path, dependency: str, version: str) -> None:
        (root / "pyproject.toml").write_text(f'''
[project]
name = "pdm-app"
version = "0.1.0"
dependencies = ["{dependency}"]
[tool.pdm]
''', encoding="utf-8")
        (root / "pdm.lock").write_text(f'''
[metadata]
lock_version = "4.5.0"
[[package]]
name = "{dependency}"
version = "{version}"
''', encoding="utf-8")

    def test_poetry_and_pdm_fleet_inventory_share_python_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            poetry = root / "poetry"
            pdm = root / "pdm"
            poetry.mkdir()
            pdm.mkdir()
            self._poetry_project(poetry, "Foo_Bar", "1.0.0")
            self._pdm_project(pdm, "foo-bar", "2.0.0")
            registry = self._registry(root, [poetry, pdm])

            code, inventory = self._json([
                "projects", "inventory", "--native", "--registry", str(registry), "--json",
            ])

            self.assertEqual(code, 0)
            self.assertEqual(inventory["failures"], [])
            self.assertEqual(len(inventory["inventory"]), 2)
            self.assertEqual(
                {item["provider"] for item in inventory["inventory"]},
                {"poetry-lock", "pdm-lock"},
            )
            self.assertEqual(
                {item["scope"] for item in inventory["inventory"]},
                {"structured-lock-package"},
            )
            self.assertEqual(
                {item["certainty"] for item in inventory["inventory"]},
                {"unconditional"},
            )

            duplicate_code, duplicates = self._json([
                "projects", "duplicates", "--native", "--registry", str(registry), "--json",
            ])
            self.assertEqual(duplicate_code, 0)
            self.assertEqual(len(duplicates["duplicates"]), 1)
            group = duplicates["duplicates"][0]
            self.assertEqual(group["normalized_name"], "foo-bar")
            self.assertEqual(group["versions"], ["1.0.0", "2.0.0"])
            self.assertEqual(group["certainty_states"], ["unconditional"])
            self.assertFalse(group["reclaimable"])

    def test_poetry_fleet_inventory_excludes_orphans_and_marks_ambiguous_candidates_possible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "poetry"
            project.mkdir()
            (project / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["parent"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (project / "poetry.lock").write_text('''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
shared = ">=1"
[[package]]
name = "shared"
version = "1.0.0"
[[package]]
name = "shared"
version = "2.0.0"
[[package]]
name = "orphan"
version = "9.9.9"
[metadata]
lock-version = "2.1"
''', encoding="utf-8")
            registry = self._registry(root, [project])

            code, data = self._json([
                "projects", "inventory", "--native", "--registry", str(registry), "--json",
            ])

            self.assertEqual(code, 0)
            rows = data["inventory"]
            self.assertEqual({item["name"] for item in rows}, {"parent", "shared"})
            shared = [item for item in rows if item["name"] == "shared"]
            self.assertEqual(len(shared), 2)
            self.assertEqual({item["certainty"] for item in shared}, {"possible"})
            parent = next(item for item in rows if item["name"] == "parent")
            self.assertEqual(parent["certainty"], "unconditional")

    def test_pnpm_fleet_inventory_preserves_workspace_occurrence_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "pnpm"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({
                "name": "pnpm-app",
                "version": "1.0.0",
                "packageManager": "pnpm@10.0.0",
            }), encoding="utf-8")
            (project / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            registry = self._registry(root, [project])

            graph = __import__("unified_project_manager.discovery", fromlist=["discover"]).discover(project)
            plan = plan_pnpm_graphs(graph)[0]
            result = PnpmGraphResult(
                plan,
                [PnpmProject(plan.component, "project:.", ".", "pnpm-app", "1.0.0", False)],
                [PnpmLogicalPackage(
                    plan.component, "project:.", "pkg:foo", "foo-alias", "foo", "2.0.0",
                    "project:.", 1, True, "dependencies", deduped=True,
                )],
                [],
                0,
            )

            with patch(
                "unified_project_manager.fleet_provider_entrypoint.execute_pnpm_graph",
                return_value=result,
            ):
                code, data = self._json([
                    "projects", "inventory", "--native", "--registry", str(registry), "--json",
                ])

            self.assertEqual(code, 0)
            row = next(item for item in data["inventory"] if item["provider"] == "pnpm-lock-tree")
            self.assertEqual(row["name"], "foo")
            self.assertEqual(row["alias"], "foo-alias")
            self.assertEqual(row["workspace_project"], "project:.")
            self.assertEqual(row["dependency_scope"], "dependencies")
            self.assertTrue(row["deduped"])

    def test_yarn_fleet_inventory_excludes_project_root_and_unreachable_stored_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "yarn"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({
                "name": "yarn-app",
                "version": "1.0.0",
                "packageManager": "yarn@4.6.0",
            }), encoding="utf-8")
            (project / "yarn.lock").write_text("# lock\n", encoding="utf-8")
            registry = self._registry(root, [project])

            graph = __import__("unified_project_manager.discovery", fromlist=["discover"]).discover(project)
            plan = plan_yarn_graphs(graph)[0]
            result = YarnGraphResult(
                plan,
                [
                    YarnResolvedPackage(plan.component, "yarn-app@workspace:.", "yarn-app", "1.0.0", "workspace:.", "workspace", True, False, None),
                    YarnResolvedPackage(plan.component, "foo@npm:2.0.0", "foo", "2.0.0", "npm:2.0.0", "npm", False, False, None),
                    YarnResolvedPackage(plan.component, "orphan@npm:9.0.0", "orphan", "9.0.0", "npm:9.0.0", "npm", False, False, None),
                ],
                [YarnDependencyEdge(plan.component, "yarn-app@workspace:.", "foo@npm:2.0.0", "foo@npm:^2")],
                0,
                yarn_version="4.6.0",
            )

            with patch(
                "unified_project_manager.fleet_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ):
                code, data = self._json([
                    "projects", "inventory", "--native", "--registry", str(registry), "--json",
                ])

            self.assertEqual(code, 0)
            yarn_rows = [item for item in data["inventory"] if item["provider"] == "yarn-berry-resolution-graph"]
            self.assertEqual(len(yarn_rows), 1)
            self.assertEqual(yarn_rows[0]["name"], "foo")
            self.assertEqual(yarn_rows[0]["scope"], "reachable-locator")
            self.assertEqual(yarn_rows[0]["occurrence"], "foo@npm:2.0.0")


if __name__ == "__main__":
    unittest.main()
