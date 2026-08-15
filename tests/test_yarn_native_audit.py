from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.discovery import discover
from unified_project_manager.native_cyclonedx import NativeCycloneDxInventory
from unified_project_manager.root_entrypoint import main
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


class YarnNativeAuditTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[object, YarnGraphResult]:
        (root / "package.json").write_text(json.dumps({
            "name":"app",
            "version":"1.0.0",
            "packageManager":"yarn@4.6.0",
        }), encoding="utf-8")
        (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
        graph = discover(root)
        yarn_plan = plan_yarn_graphs(graph)[0]
        packages, edges = parse_yarn_info(_INFO, yarn_plan.component)
        yarn = YarnGraphResult(yarn_plan, packages, edges, 0, yarn_version="4.6.0")
        return graph, yarn

    def test_public_native_audit_persists_evidence_and_returns_yarn_locator_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, yarn = self._fixture(root)
            plan = plan_security_scan(graph, native_providers=True)
            bom = {
                "bomFormat":"CycloneDX",
                "specVersion":"1.7",
                "version":1,
                "components":[{
                    "type":"library",
                    "name":"foo",
                    "version":"1.2.3",
                    "bom-ref":"pkg:npm/foo@1.2.3",
                    "purl":"pkg:npm/foo@1.2.3",
                }],
            }
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"1.2.3","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-YARN-AUDIT"}],
            }]}]}
            inventory = NativeCycloneDxInventory(
                bom,
                [],
                [],
                [],
                [],
                [],
                yarn_results=[yarn],
            )
            result = SecurityScanResult(plan, 1, report, "", bom, inventory)
            output = io.StringIO()

            with patch(
                "unified_project_manager.security_entrypoint.execute_security_scan",
                return_value=result,
            ), redirect_stdout(output):
                code = main(["audit", str(root), "--native", "--apply", "--json"])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 1)
            self.assertEqual(data["plan"]["inventory_mode"], "native-providers")
            self.assertEqual(len(data["dependency_impacts"]), 1)
            impact = data["dependency_impacts"][0]
            self.assertEqual(impact["provider"], "yarn-berry-resolution-graph")
            self.assertEqual(impact["paths"], [["app@workspace:.", "foo@npm:1.2.3"]])
            self.assertEqual(impact["evidence"]["locator"], "foo@npm:1.2.3")
            evidence_path = Path(data["evidence_path"])
            self.assertTrue(evidence_path.is_file())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["inventory_mode"], "native-providers")


if __name__ == "__main__":
    unittest.main()
