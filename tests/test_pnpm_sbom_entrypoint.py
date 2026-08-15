from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.pnpm_sbom import PnpmSbomResult
from unified_project_manager.root_entrypoint import main


class PnpmSbomEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","version":"1.0.0","packageManager":"pnpm@11"}', encoding="utf-8"
        )
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def _execute(self, plan):
        if plan.format == "cyclonedx":
            purl = "pkg:npm/foo@1.2.3?repository_url=https%3A%2F%2Fnpm.example%2F"
            document = {
                "bomFormat":"CycloneDX","specVersion":"1.7","version":1,
                "metadata":{"component":{"type":"application","name":"app","version":"1.0.0","bom-ref":"root"}},
                "components":[{"type":"library","name":"foo","version":"1.2.3","bom-ref":purl,"purl":purl}],
                "dependencies":[{"ref":"root","dependsOn":[purl]}],
            }
        else:
            document = {
                "spdxVersion":"SPDX-2.3","SPDXID":"SPDXRef-DOCUMENT",
                "packages":[{
                    "SPDXID":"SPDXRef-Foo","name":"foo","versionInfo":"1.2.3",
                    "downloadLocation":"NOASSERTION","filesAnalyzed":False,
                    "licenseConcluded":"NOASSERTION","licenseDeclared":"NOASSERTION","copyrightText":"NOASSERTION",
                    "externalRefs":[{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":"pkg:npm/foo@1.2.3"}],
                }],
                "relationships":[],
            }
        return PnpmSbomResult(plan, [document], 0)

    def test_native_cyclonedx_gets_package_identity_from_pnpm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.sbom_provider_entrypoint.execute_pnpm_sbom",
                side_effect=self._execute,
            ):
                code, document = self._json(["sbom", str(root), "--native"])

            self.assertEqual(code, 0)
            foo = next(item for item in document["components"] if item["name"] == "foo")
            self.assertEqual(
                foo["purl"],
                "pkg:npm/foo@1.2.3?repository_url=https%3A%2F%2Fnpm.example%2F",
            )
            properties = {(item["name"], item["value"]) for item in foo["properties"]}
            self.assertIn(("upm:pnpm:identity-kind", "native-lockfile-sbom"), properties)

    def test_native_spdx_gets_package_identity_from_pnpm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.sbom_provider_entrypoint.execute_pnpm_sbom",
                side_effect=self._execute,
            ):
                code, document = self._json(["sbom", str(root), "--native", "--format", "spdx"])

            self.assertEqual(code, 0)
            self.assertEqual(document["spdxVersion"], "SPDX-2.3")
            foo = next(item for item in document["packages"] if item["name"] == "foo")
            purl = next(ref["referenceLocator"] for ref in foo["externalRefs"] if ref["referenceType"] == "purl")
            self.assertEqual(purl, "pkg:npm/foo@1.2.3")


if __name__ == "__main__":
    unittest.main()
