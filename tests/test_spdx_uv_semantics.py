from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph, ResolvedPackage
from unified_project_manager.spdx import spdx_document
from unified_project_manager.uv_graph import parse_uv_lock


class SpdxUvSemanticsTests(unittest.TestCase):
    def test_marker_conditional_uv_edge_is_not_flattened_to_depends_on(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = '''
version = 1
[[package]]
name = "a"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
  { name = "b", version = "2.0.0", marker = "sys_platform == 'linux'" },
]
[[package]]
name = "b"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
'''
            uv = parse_uv_lock(lock, ".:python", root / "uv.lock")
            graph = ProjectGraph(root, [Component(
                ecosystem="python",
                path=root,
                manager="uv",
                resolved_packages=[
                    ResolvedPackage("a", "1.0.0", source="registry:https://pypi.org/simple"),
                    ResolvedPackage("b", "2.0.0", source="registry:https://pypi.org/simple"),
                ],
            )])

            document = spdx_document(
                graph,
                uv_results=[uv],
                created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            )

            purl_to_id = {
                item["externalRefs"][0]["referenceLocator"]: item["SPDXID"]
                for item in document["packages"]
                if item.get("externalRefs")
            }
            depends = {
                (item["spdxElementId"], item["relatedSpdxElement"])
                for item in document["relationships"]
                if item["relationshipType"] == "DEPENDS_ON"
            }
            self.assertIn("pkg:pypi/a@1.0.0", purl_to_id)
            self.assertIn("pkg:pypi/b@2.0.0", purl_to_id)
            self.assertNotIn(
                (purl_to_id["pkg:pypi/a@1.0.0"], purl_to_id["pkg:pypi/b@2.0.0"]),
                depends,
            )


if __name__ == "__main__":
    unittest.main()
