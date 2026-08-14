from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.registry import (
    RegistryError,
    fleet_resolved_duplicates,
    project_statuses,
    register_project,
    registered_paths,
    unregister_project,
)


class RegistryTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "project"
        project.mkdir()
        (project / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        (project / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {}}}), encoding="utf-8")
        return project

    def test_register_is_idempotent_and_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            project = self._project(root)
            path, added = register_project(project, registry)
            self.assertTrue(added)
            _, added_again = register_project(project, registry)
            self.assertFalse(added_again)
            self.assertEqual(registered_paths(registry), [path])

    def test_unregister_reports_whether_project_existed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            project = self._project(root)
            register_project(project, registry)
            _, removed = unregister_project(project, registry)
            self.assertTrue(removed)
            _, removed_again = unregister_project(project, registry)
            self.assertFalse(removed_again)

    def test_status_handles_missing_registered_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            project = self._project(root)
            register_project(project, registry)
            for child in project.iterdir():
                child.unlink()
            project.rmdir()
            status = project_statuses(registry)[0]
            self.assertFalse(status["exists"])
            self.assertIsNone(status["health"])

    def test_status_summarizes_discovered_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            project = self._project(root)
            register_project(project, registry)
            status = project_statuses(registry)[0]
            self.assertTrue(status["exists"])
            self.assertEqual(status["components"], 1)
            self.assertEqual(status["ecosystems"], ["node"])
            self.assertEqual(status["managers"], ["npm"])

    def test_register_rejects_non_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            with self.assertRaisesRegex(RegistryError, "No supported project"):
                register_project(root, registry)

    def test_fleet_resolved_duplicates_reports_cross_project_version_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.json"
            for index, version in enumerate(("1.0.0", "2.0.0")):
                project = root / f"project-{index}"
                project.mkdir()
                (project / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
                (project / "package-lock.json").write_text(json.dumps({
                    "lockfileVersion": 3,
                    "packages": {"": {}, "node_modules/foo": {"version": version}},
                }), encoding="utf-8")
                register_project(project, registry)
            groups = fleet_resolved_duplicates(registry)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["name"], "foo")
            self.assertEqual(groups[0]["projects"], 2)
            self.assertTrue(groups[0]["version_divergence"])


if __name__ == "__main__":
    unittest.main()
