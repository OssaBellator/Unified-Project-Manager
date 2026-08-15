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
                {"descriptor":"foo@npm:^1","locator":"foo@npm:1.2.3"},
            ],
        },
    },
    {"value":"foo@npm:1.2.3","children":{"Version":"1.2.3"}},
    # Yarn may expose a stored project resolution that is not reachable from an
    # active workspace. It must not become a scan/SBOM target merely because it
    # is present in the stored package set.
    {"value":"orphan@npm:9.9.9","children":{"Version":"9.9.9"}},
])


class YarnSbomScopeTests(unittest.TestCase):
    def _result(self, root: Path) -> YarnGraphResult:
        packages, edges = parse_yarn_info(_INFO, ".:node")
        return YarnGraphResult(
            YarnGraphPlan(".:node", root, root, True),
            packages,
            edges,
            0,
            yarn_version="4.6.0",
        )

    def test_cyclonedx_excludes_unreachable_npm_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = merge_yarn_cyclonedx(
                cyclonedx_bom(ProjectGraph(root, [])),
                [self._result(root)],
            )

            purls = {
                item.get("purl")
                for item in document.get("components", [])
                if item.get("purl")
            }
            self.assertEqual(purls, {"pkg:npm/foo@1.2.3"})
            self.assertNotIn("orphan", json.dumps(document))

    def test_spdx_excludes_unreachable_npm_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = spdx_document(
                ProjectGraph(root, []),
                created=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            document = merge_yarn_spdx(base, [self._result(root)])

            purls = {
                ref["referenceLocator"]
                for package in document.get("packages", [])
                for ref in package.get("externalRefs", [])
                if ref.get("referenceType") == "purl"
            }
            self.assertEqual(purls, {"pkg:npm/foo@1.2.3"})
            self.assertNotIn("orphan", json.dumps(document))


if __name__ == "__main__":
    unittest.main()
