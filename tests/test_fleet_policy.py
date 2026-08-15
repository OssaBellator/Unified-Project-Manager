from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.fleet_policy import fleet_policy_summary, registered_policy_statuses
from unified_project_manager.registry import register_project


class FleetPolicyTests(unittest.TestCase):
    def _npm(self, root: Path, name: str, *, policy: str = "") -> Path:
        project = root / name
        project.mkdir()
        (project / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        (project / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {"": {}}}), encoding="utf-8")
        if policy:
            (project / "upm.toml").write_text(policy, encoding="utf-8")
        return project

    def test_registered_policy_statuses_aggregate_pass_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            passing = self._npm(root, "passing")
            failing = self._npm(root, "failing", policy='[policy]\ndenied_managers=["npm"]\n')
            register_project(passing, registry)
            register_project(failing, registry)
            statuses = registered_policy_statuses(registry)
            summary = fleet_policy_summary(statuses)
            self.assertEqual(summary["projects"], 2)
            self.assertEqual(summary["passed"], 1)
            self.assertEqual(summary["failed"], 1)

    def test_missing_registered_root_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            project = self._npm(root, "gone")
            register_project(project, registry)
            for child in project.iterdir():
                child.unlink()
            project.rmdir()
            status = registered_policy_statuses(registry)[0]
            self.assertFalse(status["passed"])
            self.assertFalse(status["exists"])

    def test_invalid_policy_is_reported_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            project = self._npm(root, "bad", policy='[policy]\nmax_warnings="none"\n')
            register_project(project, registry)
            status = registered_policy_statuses(registry)[0]
            self.assertFalse(status["passed"])
            self.assertIn("max_warnings", status["error"])


if __name__ == "__main__":
    unittest.main()
