from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.npm_graph import NpmGraphPlan, NpmGraphResult, parse_npm_ls
from unified_project_manager.spdx import spdx_document, write_spdx


class SpdxTests(unittest.TestCase):
    def test_document_has_required_spdx_23_identity_and_package_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {"": {"name":"app","version":"1.0.0"}, "node_modules/foo": {"version":"1.2.3"}},
            }), encoding="utf-8")
            created = datetime(2026, 8, 15, 2, 30, tzinfo=timezone.utc)
            document = spdx_document(discover(root), created=created)
            self.assertEqual(document["spdxVersion"], "SPDX-2.3")
            self.assertEqual(document["dataLicense"], "CC0-1.0")
            self.assertEqual(document["SPDXID"], "SPDXRef-DOCUMENT")
            self.assertTrue(document["documentNamespace"].startswith("https://spdx.org/spdxdocs/upm-"))
            self.assertEqual(document["creationInfo"]["created"], "2026-08-15T02:30:00Z")
            package = document["packages"][0]
            self.assertEqual(package["name"], "foo")
            self.assertEqual(package["versionInfo"], "1.2.3")
            self.assertEqual(package["downloadLocation"], "NOASSERTION")
            self.assertFalse(package["filesAnalyzed"])
            self.assertEqual(package["licenseConcluded"], "NOASSERTION")
            self.assertEqual(package["licenseDeclared"], "NOASSERTION")
            self.assertEqual(package["copyrightText"], "NOASSERTION")
            self.assertEqual(package["externalRefs"][0]["referenceType"], "purl")
            self.assertEqual(package["externalRefs"][0]["referenceLocator"], "pkg:npm/foo@1.2.3")
            describes = [item for item in document["relationships"] if item["relationshipType"] == "DESCRIBES"]
            self.assertEqual(len(describes), 1)
            self.assertEqual(describes[0]["spdxElementId"], "SPDXRef-DOCUMENT")

    def test_document_namespace_is_content_deterministic_when_created_time_is_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('version=4\n[[package]]\nname="serde"\nversion="1.0.0"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n', encoding="utf-8")
            created = datetime(2026, 8, 15, tzinfo=timezone.utc)
            first = spdx_document(discover(root), created=created)
            second = spdx_document(discover(root), created=created)
            self.assertEqual(first, second)

    def test_npm_native_relationships_become_depends_on(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {"name":"app","version":"1.0.0"},
                    "node_modules/a": {"version":"1.0.0"},
                    "node_modules/a/node_modules/b": {"version":"2.0.0"},
                },
            }), encoding="utf-8")
            tree = json.dumps({"name":"app","version":"1.0.0","dependencies":{"a":{"version":"1.0.0","dependencies":{"b":{"version":"2.0.0"}}}}})
            root_name, root_version, packages, edges, problems = parse_npm_ls(tree, ".:node")
            npm = NpmGraphResult(NpmGraphPlan(".:node", root), packages, edges, 0, root_name, root_version, problems)
            document = spdx_document(discover(root), npm_results=[npm], created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            package_by_purl = {
                item["externalRefs"][0]["referenceLocator"]: item["SPDXID"]
                for item in document["packages"] if item.get("externalRefs")
            }
            depends = {
                (item["spdxElementId"], item["relatedSpdxElement"])
                for item in document["relationships"] if item["relationshipType"] == "DEPENDS_ON"
            }
            self.assertIn((package_by_purl["pkg:npm/a@1.0.0"], package_by_purl["pkg:npm/b@2.0.0"]), depends)

    def test_non_registry_cargo_package_has_no_fabricated_purl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="workspace-member"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('version=4\n[[package]]\nname="workspace-member"\nversion="0.1.0"\n', encoding="utf-8")
            document = spdx_document(discover(root), created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            package = document["packages"][0]
            self.assertNotIn("externalRefs", package)
            self.assertEqual(package["downloadLocation"], "NOASSERTION")

    def test_write_spdx_is_json_and_creates_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            document = spdx_document(discover(root), created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            target = write_spdx(document, root / "out" / "bom.spdx.json")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["spdxVersion"], "SPDX-2.3")


if __name__ == "__main__":
    unittest.main()
