from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main
from unified_project_manager.native_cyclonedx import NativeCycloneDxInventory
from unified_project_manager.registry import register_project
from unified_project_manager.security import SecurityScanResult, plan_security_scan
from unified_project_manager.yarn_graph import YarnGraphResult, parse_yarn_info, plan_yarn_graphs


_INFO = "\n".join([
    json.dumps({
        "value":"app@workspace:.",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"foo@npm:^1","locator":"foo@npm:1.2.3"},
            ],
        },
    }),
    json.dumps({"value":"foo@npm:1.2.3","children":{"Version":"1.2.3"}}),
]) + "\n"


class YarnFleetAuditTests(unittest.TestCase):
    def _project(self, root: Path) -> YarnGraphResult:
        root.mkdir()
        (root / "package.json").write_text(json.dumps({
            "name":"app","version":"1.0.0","packageManager":"yarn@4.6.0",
        }), encoding="utf-8")
        (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
        graph = discover(root)
        plan = plan_yarn_graphs(graph)[0]
        packages, edges = parse_yarn_info(_INFO, plan.component)
        return YarnGraphResult(plan, packages, edges, 0, yarn_version="4.6.0")

    def test_native_preview_does_not_execute_provider_inventory_or_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "app"
            registry = root / "projects.json"
            self._project(project)
            register_project(project, registry)
            output = io.StringIO()

            with patch(
                "unified_project_manager.fleet_security_entrypoint.execute_security_scan",
            ) as execute, redirect_stdout(output):
                code = main([
                    "projects", "audit", "--registry", str(registry),
                    "--native", "--json",
                ])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            execute.assert_not_called()
            self.assertFalse(data["executed"])
            self.assertFalse(data["provider_inventory_network"])
            self.assertEqual(data["projects"][0]["plan"]["inventory_mode"], "native-providers")

    def test_native_apply_returns_yarn_dependency_path_and_persists_native_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "app"
            registry = root / "projects.json"
            yarn = self._project(project)
            register_project(project, registry)
            graph = discover(project)
            plan = plan_security_scan(graph, native_providers=True)
            bom = {
                "bomFormat":"CycloneDX","specVersion":"1.7","version":1,
                "components":[{
                    "type":"library","name":"foo","version":"1.2.3",
                    "bom-ref":"pkg:npm/foo@1.2.3","purl":"pkg:npm/foo@1.2.3",
                }],
            }
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"1.2.3","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-FLEET-YARN"}],
            }]}]}
            inventory = NativeCycloneDxInventory(
                bom, [], [], [], [], [], yarn_results=[yarn]
            )
            result = SecurityScanResult(plan, 1, report, "", bom, inventory)
            output = io.StringIO()

            with patch(
                "unified_project_manager.fleet_security_entrypoint.execute_security_scan",
                return_value=result,
            ), redirect_stdout(output):
                code = main([
                    "projects", "audit", "--registry", str(registry),
                    "--native", "--apply", "--json",
                ])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["vulnerable_projects"], 1)
            item = data["projects"][0]
            self.assertEqual(len(item["dependency_impacts"]), 1)
            self.assertEqual(
                item["dependency_impacts"][0]["paths"],
                [["app@workspace:.", "foo@npm:1.2.3"]],
            )
            self.assertEqual(item["evidence"]["inventory_mode"], "native-providers")
            self.assertTrue(Path(item["evidence_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
