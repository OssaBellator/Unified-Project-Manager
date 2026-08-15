from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.security_impact import correlate_advisory_impact
from unified_project_manager.yarn_graph import YarnGraphPlan, YarnGraphResult, parse_yarn_info


_INFO = "\n".join([
    json.dumps({
        "value":"app@workspace:.",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"peer-user@npm:^2","locator":"peer-user@virtual:abc#npm:2.0.0"},
            ],
        },
    }),
    json.dumps({
        "value":"peer-user@virtual:abc#npm:2.0.0",
        "children":{"Version":"2.0.0"},
    }),
    json.dumps({
        "value":"peer-user@npm:2.0.0",
        "children":{"Version":"2.0.0"},
    }),
]) + "\n"


class YarnSecurityImpactTests(unittest.TestCase):
    def test_npm_advisory_keeps_yarn_virtual_locator_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages, edges = parse_yarn_info(_INFO, ".:node")
            result = YarnGraphResult(
                YarnGraphPlan(".:node", root, root, False, selected_component="packages/app:node"),
                packages,
                edges,
                0,
                yarn_version="4.6.0",
            )
            report = {"results":[{"packages":[{
                "package":{"name":"peer-user","version":"2.0.0","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-YARN"}],
            }]}]}

            impacts = correlate_advisory_impact(report, yarn_results=[result])

            self.assertEqual(len(impacts), 2)
            by_locator = {impact.evidence["locator"]: impact for impact in impacts}
            virtual = by_locator["peer-user@virtual:abc#npm:2.0.0"]
            self.assertEqual(virtual.provider, "yarn-berry-resolution-graph")
            self.assertEqual(virtual.scope, "berry-resolution-graph")
            self.assertEqual(virtual.component, "packages/app:node")
            self.assertEqual(
                virtual.paths,
                (("app@workspace:.", "peer-user@virtual:abc#npm:2.0.0"),),
            )
            self.assertTrue(virtual.evidence["virtual"])
            base = by_locator["peer-user@npm:2.0.0"]
            self.assertEqual(
                base.paths,
                ((
                    "app@workspace:.",
                    "peer-user@virtual:abc#npm:2.0.0",
                    "peer-user@npm:2.0.0",
                ),),
            )
            self.assertFalse(base.evidence["virtual"])


if __name__ == "__main__":
    unittest.main()
