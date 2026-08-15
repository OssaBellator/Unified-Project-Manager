from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.yarn_graph import YarnGraphPlan, YarnGraphResult, parse_yarn_info
from unified_project_manager.yarn_impact import analyze_yarn_impact


def _ndjson(records: list[dict]) -> str:
    return "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n"


class YarnImpactTests(unittest.TestCase):
    def test_virtual_and_devirtualized_occurrences_remain_distinct(self) -> None:
        output = _ndjson([
            {
                "value":"app@workspace:.",
                "children":{
                    "Version":"1.0.0",
                    "Dependencies":[
                        {"descriptor":"peer-user@npm:^2","locator":"peer-user@virtual:abc#npm:2.0.0"},
                    ],
                },
            },
            {
                "value":"peer-user@virtual:abc#npm:2.0.0",
                "children":{"Version":"2.0.0"},
            },
            {
                "value":"peer-user@npm:2.0.0",
                "children":{
                    "Version":"2.0.0",
                    "Dependencies":[
                        {"descriptor":"foo@npm:^1","locator":"foo@npm:1.2.3"},
                    ],
                },
            },
            {"value":"foo@npm:1.2.3","children":{"Version":"1.2.3"}},
        ])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages, edges = parse_yarn_info(output, ".:node")
            result = YarnGraphResult(
                YarnGraphPlan(".:node", root, root, False, selected_component="packages/app:node"),
                packages,
                edges,
                0,
                yarn_version="4.6.0",
            )

            impacts = analyze_yarn_impact(result, "peer-user")

            self.assertEqual(len(impacts), 2)
            by_locator = {impact.locator: impact for impact in impacts}
            self.assertEqual(
                by_locator["peer-user@virtual:abc#npm:2.0.0"].root_paths,
                (("app@workspace:.", "peer-user@virtual:abc#npm:2.0.0"),),
            )
            self.assertEqual(
                by_locator["peer-user@npm:2.0.0"].root_paths,
                ((
                    "app@workspace:.",
                    "peer-user@virtual:abc#npm:2.0.0",
                    "peer-user@npm:2.0.0",
                ),),
            )
            self.assertEqual(
                {impact.component for impact in impacts},
                {"packages/app:node"},
            )

    def test_unreachable_project_wide_records_are_not_reported_as_impact(self) -> None:
        output = _ndjson([
            {"value":"app@workspace:.","children":{"Version":"1.0.0"}},
            {"value":"orphan@npm:9.9.9","children":{"Version":"9.9.9"}},
        ])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages, edges = parse_yarn_info(output, ".:node")
            result = YarnGraphResult(YarnGraphPlan(".:node", root, root, True), packages, edges, 0)
            self.assertEqual(analyze_yarn_impact(result, "orphan"), [])


if __name__ == "__main__":
    unittest.main()
