from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.registry import register_project
from unified_project_manager.security import SecurityScanPlan, SecurityScanResult


class FleetSecurityTests(unittest.TestCase):
    def _npm_project(self, root: Path, name: str) -> None:
        root.mkdir()
        (root / "package.json").write_text(
            json.dumps({"name": name, "version": "1.0.0", "packageManager": "npm@11"}),
            encoding="utf-8",
        )
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": name, "version": "1.0.0"},
                "node_modules/foo": {"version": "1.2.3"},
            },
        }), encoding="utf-8")

    def test_preview_does_not_run_scanner_and_keeps_missing_project_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            project = root / "app"
            self._npm_project(project, "app")
            register_project(project, registry)
            missing = root / "missing"
            data = json.loads(registry.read_text(encoding="utf-8"))
            data["projects"].append(str(missing))
            registry.write_text(json.dumps(data), encoding="utf-8")

            output = io.StringIO()
            with patch("unified_project_manager.fleet_security_entrypoint.execute_security_scan") as execute, redirect_stdout(output):
                code = main(["projects", "audit", "--registry", str(registry), "--json"])
            execute.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(payload["executed"])
            self.assertTrue(payload["network_may_be_used"])
            self.assertEqual(payload["missing"], [str(missing)])
            self.assertEqual(len(payload["projects"]), 1)

    def test_apply_aggregates_findings_without_calling_them_scanner_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            one = root / "one"
            two = root / "two"
            self._npm_project(one, "one")
            self._npm_project(two, "two")
            register_project(one, registry)
            register_project(two, registry)

            clean = SecurityScanResult(SecurityScanPlan(one, 1, True, False), 0, {"results": []})
            vulnerable = SecurityScanResult(SecurityScanPlan(two, 1, True, False), 1, {
                "results": [{"packages": [{"vulnerabilities": [{"id": "GHSA-test"}]}]}],
            })
            output = io.StringIO()
            with patch(
                "unified_project_manager.fleet_security_entrypoint.execute_security_scan",
                side_effect=[clean, vulnerable],
            ), redirect_stdout(output):
                code = main(["projects", "audit", "--registry", str(registry), "--apply", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(payload["summary"]["vulnerable_projects"], 1)
            self.assertEqual(payload["summary"]["scanner_failures"], 0)
            self.assertEqual(payload["summary"]["unique_vulnerabilities"], 1)

    def test_apply_returns_scanner_failure_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            project = root / "app"
            self._npm_project(project, "app")
            register_project(project, registry)
            failure = SecurityScanResult(SecurityScanPlan(project, 1, True, False), 127, None, "scanner missing")
            output = io.StringIO()
            with patch("unified_project_manager.fleet_security_entrypoint.execute_security_scan", return_value=failure), redirect_stdout(output):
                code = main(["projects", "audit", "--registry", str(registry), "--apply", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["summary"]["scanner_failures"], 1)
            self.assertEqual(payload["summary"]["vulnerable_projects"], 0)


if __name__ == "__main__":
    unittest.main()
