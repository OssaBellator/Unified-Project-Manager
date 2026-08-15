from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.update_operation import UpdateOperationError, plan_update


class UpdateOperationTests(unittest.TestCase):
    def _graph(
        self,
        root: Path,
        ecosystem: str,
        manager: str,
        *,
        metadata: dict | None = None,
        lockfiles: list[str] | None = None,
    ) -> ProjectGraph:
        component = Component(
            ecosystem,
            root,
            manager,
            lockfiles=list(lockfiles or []),
            metadata=dict(metadata or {}),
        )
        return ProjectGraph(root, [component])

    def test_node_managers_use_native_update_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("npm", ("npm", "update", "react"), False),
                ("pnpm", ("pnpm", "update", "react"), False),
                ("bun", ("bun", "update", "react"), True),
            )
            for manager, expected, manifest_may_change in cases:
                with self.subTest(manager=manager):
                    plan = plan_update(
                        self._graph(root, "node", manager),
                        packages=("react",),
                    )
                    self.assertEqual(plan.argv, expected)
                    self.assertEqual(plan.update_scope, "selected")
                    self.assertEqual(plan.manifest_may_change, manifest_may_change)
                    self.assertTrue(plan.native_state_may_change)
                    self.assertTrue(plan.installed_state_may_change)
                    self.assertTrue(plan.network_may_be_used)

    def test_yarn_classic_and_modern_commands_are_version_aware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            classic = plan_update(
                self._graph(
                    root,
                    "node",
                    "yarn",
                    metadata={"package_manager_declared": "yarn@1.22.22"},
                ),
                packages=("react",),
            )
            modern = plan_update(
                self._graph(
                    root,
                    "node",
                    "yarn",
                    metadata={"package_manager_declared": "yarn@4.9.2"},
                ),
                packages=("react",),
            )
            modern_all = plan_update(
                self._graph(
                    root,
                    "node",
                    "yarn",
                    metadata={"package_manager_declared": "yarn@4.9.2"},
                ),
            )
            self.assertEqual(classic.argv, ("yarn", "upgrade", "react"))
            self.assertEqual(modern.argv, ("yarn", "up", "react"))
            self.assertEqual(modern_all.argv, ("yarn", "up", "*"))
            self.assertEqual(modern_all.update_scope, "all")
            self.assertIn("without shell expansion", modern_all.semantics)

    def test_uv_update_changes_lock_resolution_but_not_installed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root, "python", "uv", lockfiles=["uv.lock"])

            all_plan = plan_update(graph)
            selected = plan_update(graph, packages=("requests", "urllib3"))

            self.assertEqual(all_plan.argv, ("uv", "lock", "--upgrade"))
            self.assertEqual(
                selected.argv,
                (
                    "uv", "lock",
                    "--upgrade-package", "requests",
                    "--upgrade-package", "urllib3",
                ),
            )
            self.assertFalse(all_plan.manifest_may_change)
            self.assertTrue(all_plan.native_state_may_change)
            self.assertFalse(all_plan.installed_state_may_change)
            self.assertIn("synchronization remains a separate", all_plan.semantics)

    def test_poetry_and_pdm_delegate_to_native_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for manager in ("poetry", "pdm"):
                with self.subTest(manager=manager):
                    plan = plan_update(
                        self._graph(root, "python", manager),
                        packages=("requests",),
                    )
                    self.assertEqual(plan.argv, (manager, "update", "requests"))
                    self.assertFalse(plan.manifest_may_change)
                    self.assertTrue(plan.native_state_may_change)
                    self.assertTrue(plan.installed_state_may_change)

    def test_cargo_updates_lock_selections_and_repeats_package_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root, "rust", "cargo", lockfiles=["Cargo.lock"])

            all_plan = plan_update(graph)
            selected = plan_update(graph, packages=("serde", "syn@2.0.0"))

            self.assertEqual(all_plan.argv, ("cargo", "update"))
            self.assertEqual(
                selected.argv,
                ("cargo", "update", "-p", "serde", "-p", "syn@2.0.0"),
            )
            self.assertFalse(all_plan.manifest_may_change)
            self.assertTrue(all_plan.native_state_may_change)
            self.assertFalse(all_plan.installed_state_may_change)

    def test_go_requires_explicit_targets_and_normalizes_missing_versions_to_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root, "go", "go")

            with self.assertRaisesRegex(UpdateOperationError, "explicit module/package targets"):
                plan_update(graph)

            plan = plan_update(
                graph,
                packages=("golang.org/x/text", "example.com/lib@v1.2.3"),
            )
            self.assertEqual(
                plan.argv,
                (
                    "go", "get",
                    "golang.org/x/text@latest",
                    "example.com/lib@v1.2.3",
                ),
            )
            self.assertEqual(plan.update_scope, "selected")
            self.assertTrue(plan.manifest_may_change)
            self.assertTrue(plan.native_state_may_change)
            self.assertFalse(plan.installed_state_may_change)

    def test_pip_refuses_to_confuse_environment_upgrade_with_project_state_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root, "python", "pip")
            with self.assertRaisesRegex(UpdateOperationError, "cannot safely update project desired state"):
                plan_update(graph, packages=("requests",))

    def test_component_selection_and_manager_ownership_remain_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = Component("node", root / "frontend", "npm")
            backend = Component("rust", root / "backend", "cargo")
            graph = ProjectGraph(root, [frontend, backend])

            with self.assertRaisesRegex(UpdateOperationError, "Multiple components"):
                plan_update(graph)
            selected = plan_update(graph, selector="frontend", packages=("react",))
            self.assertEqual(selected.component, "frontend:node")
            self.assertEqual(selected.argv, ("npm", "update", "react"))

            conflicted = self._graph(
                root,
                "node",
                "npm",
                metadata={
                    "manager_from_manifest": "pnpm",
                    "manager_from_lock": "npm",
                },
            )
            with self.assertRaisesRegex(UpdateOperationError, "manifest declares pnpm"):
                plan_update(conflicted, packages=("react",))

    def test_empty_package_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(UpdateOperationError, "non-empty"):
                plan_update(self._graph(root, "node", "npm"), packages=("",))


if __name__ == "__main__":
    unittest.main()
