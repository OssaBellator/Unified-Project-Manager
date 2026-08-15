from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.npm_sbom import NpmSbomResult
from unified_project_manager.root_entrypoint import main


class NpmSbomEntrypointTests(unittest.TestCase):
    def _workspace(self, root: Path) -> None:
        (root / "package.json").write_text(json.dumps({
            "name":"root","version":"1.0.0","private":True,
            "packageManager":"npm@11","workspaces":["packages/*"],
        }), encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
        for name in ("app", "other"):
            member = root / "packages" / name
            member.mkdir(parents=True)
            (member / "package.json").write_text(f'{{"name":"{name}","version":"1.0.0"}}', encoding="utf-8")

    def _execute(self, plan):
        if plan.format == "cyclonedx":
            document = {
                "bomFormat":"CycloneDX","specVersion":"1.5","version":1,
                "metadata":{"component":{"bom-ref":"root@1.0.0","type":"library","name":"root","version":"1.0.0","purl":"pkg:npm/root@1.0.0"}},
                "components":[
                    {"bom-ref":"app@1.0.0","type":"library","name":"app","version":"1.0.0","purl":"pkg:npm/app@1.0.0"},
                    {"bom-ref":"foo@2.0.0","type":"library","name":"foo","version":"2.0.0","purl":"pkg:npm/foo@2.0.0"},
                ],
                "dependencies":[
                    {"ref":"root@1.0.0","dependsOn":["app@1.0.0"]},
                    {"ref":"app@1.0.0","dependsOn":["foo@2.0.0"]},
                ],
            }
        else:
            document = {
                "spdxVersion":"SPDX-2.3","SPDXID":"SPDXRef-DOCUMENT",
                "packages":[{
                    "SPDXID":"SPDXRef-App","name":"app","versionInfo":"1.0.0",
                    "externalRefs":[{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":"pkg:npm/app@1.0.0"}],
                }],
                "relationships":[],
            }
        return NpmSbomResult(plan, document, 0)

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_selected_workspace_native_cyclonedx_uses_exact_workspace_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            observed = []

            def execute(plan):
                observed.append(plan)
                return self._execute(plan)

            with patch("unified_project_manager.sbom_provider_entrypoint.execute_npm_sbom", side_effect=execute):
                code, document = self._json([
                    "sbom", str(root), "--native", "--component", "app"
                ])

            self.assertEqual(code, 0)
            self.assertEqual(observed[0].workspace_selector, "./packages/app")
            self.assertEqual(document["specVersion"], "1.7")
            names = {item["name"] for item in document["components"]}
            self.assertIn("app", names)
            self.assertIn("foo", names)
            self.assertNotIn("other", names)

    def test_selected_workspace_native_spdx_uses_npm_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            with patch("unified_project_manager.sbom_provider_entrypoint.execute_npm_sbom", side_effect=self._execute):
                code, document = self._json([
                    "sbom", str(root), "--native", "--format", "spdx", "--component", "app"
                ])

            self.assertEqual(code, 0)
            self.assertEqual(document["spdxVersion"], "SPDX-2.3")
            self.assertTrue(any(item["name"] == "app" for item in document["packages"]))
            self.assertFalse(any(item["name"] == "other" for item in document["packages"]))


if __name__ == "__main__":
    unittest.main()
