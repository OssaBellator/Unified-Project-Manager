from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.uv_workspace import UvWorkspaceError, inspect_uv_workspace, uv_workspace_ownership
from unified_project_manager.uv_workspace_graph import plan_uv_workspace_graphs, uv_provider_component_keys


class UvWorkspaceTests(unittest.TestCase):
    def _project(self, path: Path, name: str, extra: str = "") -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\n{extra}', encoding="utf-8"
        )

    def test_workspace_members_share_one_root_uv_lock_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            (root / "uv.lock").write_text('version=1\n', encoding="utf-8")
            self._project(root / "packages" / "a", "a")
            self._project(root / "packages" / "b", "b")
            graph = discover(root)

            plans = plan_uv_workspace_graphs(graph)

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:python")
            self.assertEqual(plans[0].lockfile, root / "uv.lock")
            self.assertEqual(
                uv_provider_component_keys(graph, plans),
                {".:python", "packages/a:python", "packages/b:python"},
            )

    def test_member_selector_promotes_to_authoritative_root_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            (root / "uv.lock").write_text('version=1\n', encoding="utf-8")
            self._project(root / "packages" / "app", "app")
            graph = discover(root)

            plans = plan_uv_workspace_graphs(graph, selector="app")

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:python")
            self.assertEqual(plans[0].lockfile, root / "uv.lock")

    def test_excluded_member_with_own_lock_remains_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(
                root,
                "root",
                '[tool.uv.workspace]\nmembers=["packages/*"]\nexclude=["packages/tool"]\n',
            )
            (root / "uv.lock").write_text('version=1\n', encoding="utf-8")
            self._project(root / "packages" / "app", "app")
            tool = root / "packages" / "tool"
            self._project(tool, "tool", '[tool.uv]\n')
            (tool / "uv.lock").write_text('version=1\n', encoding="utf-8")
            graph = discover(root)

            plans = plan_uv_workspace_graphs(graph)

            self.assertEqual({plan.lockfile for plan in plans}, {root / "uv.lock", tool / "uv.lock"})
            _roots, owners = uv_workspace_ownership(graph)
            self.assertNotIn(tool.resolve(), owners)

    def test_nested_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            (root / "uv.lock").write_text('version=1\n', encoding="utf-8")
            member = root / "packages" / "nested"
            self._project(member, "nested", '[tool.uv.workspace]\nmembers=[]\n')
            (member / "uv.lock").write_text('version=1\n', encoding="utf-8")
            graph = discover(root)
            root_component = next(component for component in graph.components if component.path == root)

            with self.assertRaisesRegex(UvWorkspaceError, "Nested uv workspace"):
                inspect_uv_workspace(graph, root_component)

    def test_workspace_without_root_lock_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            self._project(root / "packages" / "app", "app")
            graph = discover(root)

            with self.assertRaisesRegex(UvWorkspaceError, "no authoritative uv.lock"):
                uv_workspace_ownership(graph)

    def test_unmatched_member_pattern_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["missing/*"]\n')
            (root / "uv.lock").write_text('version=1\n', encoding="utf-8")
            graph = discover(root)
            root_component = graph.components[0]
            workspace = inspect_uv_workspace(graph, root_component)
            assert workspace is not None
            self.assertEqual(workspace.unmatched_patterns, ("missing/*",))


if __name__ == "__main__":
    unittest.main()
