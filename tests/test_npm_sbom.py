from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.npm_sbom import NpmSbomPlan, NpmSbomResult, execute_npm_sbom, plan_npm_sboms
from unified_project_manager.npm_sbom_merge import merge_npm_cyclonedx, merge_npm_spdx


class NpmSbomTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        (root / "package.json").write_text(json.dumps({
            "name":"root","version":"1.0.0","private":True,
            "packageManager":"npm@11","workspaces":["packages/*"],
        }), encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"name":"app","version":"1.0.0"}', encoding="utf-8")
        return member

    def test_workspace_member_uses_exact_root_relative_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            plans = plan_npm_sboms(discover(root), "cyclonedx", selector="app")
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:node")
            self.assertEqual(plans[0].cwd, root)
            self.assertEqual(plans[0].workspace_selector, "./packages/app")
            self.assertEqual(plans[0].argv[-2:], ("--workspace", "./packages/app"))
            self.assertIn("--package-lock-only", plans[0].argv)

    def test_execute_uses_exact_npm_binary_and_parses_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = NpmSbomPlan(".:node", root, "cyclonedx")
            document = {"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, json.dumps(document), "")

            result = execute_npm_sbom(plan, run=run, which=lambda _name: "/tools/npm")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0][0], "/tools/npm")
            self.assertIn("--package-lock-only", calls[0][0])
            self.assertEqual(result.document["specVersion"], "1.5")

    def test_cyclonedx_merge_keeps_aggregate_17_and_native_workspace_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = NpmSbomPlan(".:node", root, "cyclonedx", "./packages/app")
            native = {
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
            base = {"bomFormat":"CycloneDX","specVersion":"1.7","version":1,"components":[]}
            result = NpmSbomResult(plan, native, 0)

            merged = merge_npm_cyclonedx(base, [result])

            self.assertEqual(merged["specVersion"], "1.7")
            refs = {item["bom-ref"] for item in merged["components"]}
            self.assertIn("pkg:npm/app@1.0.0", refs)
            deps = {item["ref"]: item["dependsOn"] for item in merged["dependencies"]}
            self.assertEqual(deps["pkg:npm/app@1.0.0"], ["pkg:npm/foo@2.0.0"])
            app = next(item for item in merged["components"] if item["bom-ref"] == "pkg:npm/app@1.0.0")
            props = {(item["name"], item["value"]) for item in app["properties"]}
            self.assertIn(("upm:npm:workspace-selector", "./packages/app"), props)

    def test_spdx_merge_remaps_native_dependencies_and_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = NpmSbomPlan(".:node", root, "spdx")
            native = {
                "spdxVersion":"SPDX-2.3","SPDXID":"SPDXRef-DOCUMENT",
                "packages":[
                    {"SPDXID":"SPDXRef-A","name":"a","versionInfo":"1","externalRefs":[{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":"pkg:npm/a@1"}]},
                    {"SPDXID":"SPDXRef-B","name":"b","versionInfo":"2","externalRefs":[{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":"pkg:npm/b@2"}]},
                ],
                "relationships":[{"spdxElementId":"SPDXRef-A","relationshipType":"DEPENDS_ON","relatedSpdxElement":"SPDXRef-B"}],
            }
            base = {"spdxVersion":"SPDX-2.3","dataLicense":"CC0-1.0","SPDXID":"SPDXRef-DOCUMENT","name":"x","documentNamespace":"old","creationInfo":{"created":"2026-01-01T00:00:00Z","creators":["Tool: UPM"]},"packages":[],"relationships":[]}
            result = NpmSbomResult(plan, native, 0)

            merged = merge_npm_spdx(base, [result])

            self.assertNotEqual(merged["documentNamespace"], "old")
            purls = {
                ref["referenceLocator"]: package["SPDXID"]
                for package in merged["packages"]
                for ref in package.get("externalRefs", [])
                if ref.get("referenceType") == "purl"
            }
            depends = {(item["spdxElementId"], item["relatedSpdxElement"]) for item in merged["relationships"] if item["relationshipType"] == "DEPENDS_ON"}
            self.assertIn((purls["pkg:npm/a@1"], purls["pkg:npm/b@2"]), depends)


if __name__ == "__main__":
    unittest.main()
