from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.dedupe_operation import DedupeOperationError, plan_dedupe
from unified_project_manager.models import Component, ProjectGraph


class DedupeOperationTests(unittest.TestCase):
    def _graph(self, root: Path, manager: str, metadata: dict | None = None) -> ProjectGraph:
        return ProjectGraph(root, [
            Component("node", root, manager, metadata=dict(metadata or {})),
        ])

    def test_npm_and_pnpm_use_first_party_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for manager in ("npm", "pnpm"):
                with self.subTest(manager=manager):
                    plan = plan_dedupe(self._graph(root, manager))
                    self.assertEqual(plan.argv, (manager, "dedupe"))
                    self.assertFalse(plan.manifest_may_change)
                    self.assertTrue(plan.native_state_may_change)
                    self.assertTrue(plan.installed_state_may_change)
                    self.assertTrue(plan.network_may_be_used)

    def test_modern_yarn_is_supported_but_classic_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modern = plan_dedupe(self._graph(
                root,
                "yarn",
                {"package_manager_declared": "yarn@4.9.2"},
            ))
            self.assertEqual(modern.argv, ("yarn", "dedupe"))

            with self.assertRaisesRegex(DedupeOperationError, "Yarn Classic"):
                plan_dedupe(self._graph(
                    root,
                    "yarn",
                    {"package_manager_declared": "yarn@1.22.22"},
                ))

    def test_bun_is_not_given_an_invented_dedupe_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(DedupeOperationError, "No UPM-configured"):
                plan_dedupe(self._graph(root, "bun"))

    def test_non_node_ecosystems_remain_analysis_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ecosystem, manager in (("rust", "cargo"), ("python", "uv"), ("go", "go")):
                with self.subTest(ecosystem=ecosystem):
                    graph = ProjectGraph(root, [Component(ecosystem, root, manager)])
                    with self.assertRaisesRegex(DedupeOperationError, "No generic dedupe mutation"):
                        plan_dedupe(graph)

    def test_ambiguous_component_selection_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("node", root / "a", "npm"),
                Component("node", root / "b", "pnpm"),
            ])
            with self.assertRaisesRegex(DedupeOperationError, "Multiple components"):
                plan_dedupe(graph)
            selected = plan_dedupe(graph, selector="b")
            self.assertEqual(selected.component, "b:node")
            self.assertEqual(selected.argv, ("pnpm", "dedupe"))

    def test_manager_ownership_conflict_blocks_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root, "npm", {
                "manager_from_manifest": "pnpm",
                "manager_from_lock": "npm",
            })
            with self.assertRaisesRegex(DedupeOperationError, "manifest declares pnpm"):
                plan_dedupe(graph)


if __name__ == "__main__":
    unittest.main()
