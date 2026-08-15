from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.models import ProjectGraph
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.spdx import spdx_document
from unified_project_manager.yarn_graph import YarnGraphPlan, YarnGraphResult, parse_yarn_info
from unified_project_manager.yarn_sbom_merge import merge_yarn_cyclonedx, merge_yarn_spdx


def _ndjson(records: list[dict]) -> str:
    return "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n"


_INFO = _ndjson([
    {
        "value":"app@workspace:.",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"peer-user@npm:^2","locator":"peer-user@virtual:abc#npm:2.0.0"},
                {"descriptor":"local-git@git:https://example.invalid/x.git","locator":"local-git@git:https://example.invalid/x.git#commit=abc"},
            ],
        },
    },
    {"value":"peer-user@virtual:abc#npm:2.0.0","children":{"Version":"2.0.0"}},
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
    {"value":"local-git@git:https://example.invalid/x.git#commit=abc","children":{"Version":"3.0.0"}},
])


class YarnSbomMergeTests(unittest.TestCase):
    def _result(self, root: Path) -> YarnGraphResult:
        packages, edges = parse_yarn_info(_INFO, ".:node")
        return YarnGraphResult(
            YarnGraphPlan(".:node", root, root, False),
            packages,
            edges,
            0,
            yarn_version="4.6.0",
        )

    def test_cyclonedx_adds_only_npm_protocol_packages_and_dedupes_virtuals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [])

            document = merge_yarn_cyclonedx(cyclonedx_bom(graph), [self._result(root)])

            purls = {item.get("purl") for item in document["components"]}
            self.assertEqual(purls, {"pkg:npm/peer-user@2.0.0", "pkg:npm/foo@1.2.3"})
            peer = next(item for item in document["components"] if item.get("purl") == "pkg:npm/peer-user@2.0.0")
            self.assertIn(
                {"name":"upm:yarn:locator-occurrences","value":"2"},
                peer.get("properties", []),
            )
            self.assertIn(
                {"name":"upm:yarn:virtual-occurrences","value":"1"},
                peer.get("properties", []),
            )
            dependencies = {
                item["ref"]: set(item.get("dependsOn", []))
                for item in document.get("dependencies", [])
            }
            self.assertEqual(
                dependencies["pkg:npm/peer-user@2.0.0"],
                {"pkg:npm/foo@1.2.3"},
            )
            self.assertNotIn("local-git", json.dumps(document))

    def test_spdx_uses_same_registry_identity_and_relationship_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [])
            base = spdx_document(graph, created=datetime(2026, 1, 1, tzinfo=timezone.utc))

            document = merge_yarn_spdx(base, [self._result(root)])

            purls = {
                ref["referenceLocator"]
                for package in document["packages"]
                for ref in package.get("externalRefs", [])
                if ref.get("referenceType") == "purl"
            }
            self.assertEqual(purls, {"pkg:npm/peer-user@2.0.0", "pkg:npm/foo@1.2.3"})
            by_name = {package["name"]: package["SPDXID"] for package in document["packages"]}
            self.assertIn({
                "spdxElementId": by_name["peer-user"],
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": by_name["foo"],
            }, document["relationships"])
            self.assertNotIn("local-git", json.dumps(document))


if __name__ == "__main__":
    unittest.main()
