from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.sbom import cyclonedx_bom, purl_for, write_cyclonedx


class SbomTests(unittest.TestCase):
    def test_purl_mappings(self) -> None:
        self.assertEqual(purl_for("node", "@angular/core", "20.0.0"), "pkg:npm/%40angular/core@20.0.0")
        self.assertEqual(purl_for("python", "My_Package", "1.2.3"), "pkg:pypi/my-package@1.2.3")
        self.assertEqual(purl_for("rust", "serde", "1.0.219"), "pkg:cargo/serde@1.0.219")

    def test_cyclonedx_deduplicates_same_package_version_across_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/foo": {"version": "1.0.0"},
                    "node_modules/parent/node_modules/foo": {"version": "1.0.0"},
                    "node_modules/bar": {"version": "2.0.0"},
                },
            }), encoding="utf-8")
            bom = cyclonedx_bom(discover(root))
            self.assertEqual(bom["bomFormat"], "CycloneDX")
            self.assertEqual(bom["specVersion"], "1.7")
            self.assertEqual(len(bom["components"]), 2)
            self.assertEqual({item["purl"] for item in bom["components"]}, {"pkg:npm/foo@1.0.0", "pkg:npm/bar@2.0.0"})

    def test_cyclonedx_uses_resolved_versions_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11","dependencies":{"foo":"^1"}}', encoding="utf-8")
            bom = cyclonedx_bom(discover(root))
            self.assertEqual(bom["components"], [])

    def test_non_registry_resolution_does_not_get_registry_purl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="workspace-member"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('version = 4\n[[package]]\nname="workspace-member"\nversion="0.1.0"\n', encoding="utf-8")
            component = cyclonedx_bom(discover(root))["components"][0]
            self.assertNotIn("purl", component)
            self.assertTrue(component["bom-ref"].startswith("urn:upm:component:sha256:"))

    def test_write_cyclonedx_is_deterministic_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('version = 4\n[[package]]\nname="serde"\nversion="1.0.0"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n', encoding="utf-8")
            output = root / "out" / "bom.json"
            written = write_cyclonedx(discover(root), output)
            data = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(data["components"][0]["purl"], "pkg:cargo/serde@1.0.0")


if __name__ == "__main__":
    unittest.main()
