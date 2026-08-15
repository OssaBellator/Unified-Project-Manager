from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.pnpm_sbom import (
    PnpmSbomPlan,
    PnpmSbomResult,
    execute_pnpm_sbom,
    parse_pnpm_sbom_output,
    plan_pnpm_sboms,
)
from unified_project_manager.pnpm_sbom_merge import merge_pnpm_cyclonedx, merge_pnpm_spdx


class PnpmSbomTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        (root / "package.json").write_text(
            '{"name":"root","version":"1.0.0","private":true,"packageManager":"pnpm@11"}', encoding="utf-8"
        )
        (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"name":"app","version":"0.1.0"}', encoding="utf-8")
        return member

    def test_workspace_all_uses_split_and_member_selector_uses_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            graph = discover(root)

            all_plans = plan_pnpm_sboms(graph, "cyclonedx")
            selected = plan_pnpm_sboms(graph, "spdx", selector="app")

            self.assertEqual(len(all_plans), 1)
            self.assertTrue(all_plans[0].split)
            self.assertIn("--split", all_plans[0].argv)
            self.assertEqual(selected[0].filter_selector, "app")
            self.assertNotIn("--split", selected[0].argv)
            self.assertIn("--lockfile-only", selected[0].argv)

    def test_split_parser_accepts_ndjson_and_execution_uses_resolved_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PnpmSbomPlan(".:node", root, "cyclonedx", split=True)
            documents = [
                {"bomFormat":"CycloneDX","specVersion":"1.7","components":[]},
                {"bomFormat":"CycloneDX","specVersion":"1.7","components":[]},
            ]
            output = "\n".join(json.dumps(document, separators=(",", ":")) for document in documents)
            self.assertEqual(len(parse_pnpm_sbom_output(output, plan)), 2)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, output, "")

            result = execute_pnpm_sbom(plan, run=run, which=lambda _name: "/tools/pnpm")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0][0], "/tools/pnpm")
            self.assertIn("--sbom-format", calls[0][0])
            self.assertIn("--lockfile-only", calls[0][0])

    def test_cyclonedx_merge_preserves_native_registry_purl_and_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PnpmSbomPlan(".:node", root, "cyclonedx")
            root_ref = "urn:root"
            a = "pkg:npm/a@1.0.0?repository_url=https%3A%2F%2Fnpm.example%2F"
            b = "pkg:npm/b@2.0.0"
            native = {
                "bomFormat":"CycloneDX","specVersion":"1.7",
                "metadata":{"component":{"type":"application","name":"app","version":"1.0.0","bom-ref":root_ref}},
                "components":[
                    {"type":"library","name":"a","version":"1.0.0","bom-ref":a,"purl":a},
                    {"type":"library","name":"b","version":"2.0.0","bom-ref":b,"purl":b},
                ],
                "dependencies":[
                    {"ref":root_ref,"dependsOn":[a]},
                    {"ref":a,"dependsOn":[b]},
                ],
            }
            result = PnpmSbomResult(plan, [native], 0)
            base = {"bomFormat":"CycloneDX","specVersion":"1.7","version":1,"components":[]}

            merged = merge_pnpm_cyclonedx(base, [result])

            by_ref = {item["bom-ref"]: item for item in merged["components"]}
            self.assertIn(a, by_ref)
            self.assertEqual(by_ref[a]["purl"], a)
            deps = {item["ref"]: item["dependsOn"] for item in merged["dependencies"]}
            self.assertEqual(deps[a], [b])
            root_component = next(item for item in merged["components"] if item["name"] == "app")
            properties = {(item["name"], item["value"]) for item in root_component["properties"]}
            self.assertIn(("upm:pnpm:project-component", "true"), properties)

    def test_spdx_merge_remaps_native_ids_and_recomputes_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PnpmSbomPlan(".:node", root, "spdx")
            native = {
                "spdxVersion":"SPDX-2.3","SPDXID":"SPDXRef-DOCUMENT",
                "packages":[
                    {"SPDXID":"SPDXRef-A","name":"a","versionInfo":"1.0.0","downloadLocation":"NOASSERTION","filesAnalyzed":False,"licenseConcluded":"NOASSERTION","licenseDeclared":"NOASSERTION","copyrightText":"NOASSERTION","externalRefs":[{"referenceType":"purl","referenceLocator":"pkg:npm/a@1.0.0","referenceCategory":"PACKAGE-MANAGER"}]},
                    {"SPDXID":"SPDXRef-B","name":"b","versionInfo":"2.0.0","downloadLocation":"NOASSERTION","filesAnalyzed":False,"licenseConcluded":"NOASSERTION","licenseDeclared":"NOASSERTION","copyrightText":"NOASSERTION","externalRefs":[{"referenceType":"purl","referenceLocator":"pkg:npm/b@2.0.0","referenceCategory":"PACKAGE-MANAGER"}]},
                ],
                "relationships":[{"spdxElementId":"SPDXRef-A","relationshipType":"DEPENDS_ON","relatedSpdxElement":"SPDXRef-B"}],
            }
            result = PnpmSbomResult(plan, [native], 0)
            base = {"spdxVersion":"SPDX-2.3","dataLicense":"CC0-1.0","SPDXID":"SPDXRef-DOCUMENT","name":"x","documentNamespace":"old","creationInfo":{"created":"2026-01-01T00:00:00Z","creators":["Tool: UPM"]},"packages":[],"relationships":[]}

            merged = merge_pnpm_spdx(base, [result])

            self.assertNotEqual(merged["documentNamespace"], "old")
            purls = {
                ref["referenceLocator"]: package["SPDXID"]
                for package in merged["packages"]
                for ref in package.get("externalRefs", [])
                if ref.get("referenceType") == "purl"
            }
            depends = {
                (item["spdxElementId"], item["relatedSpdxElement"])
                for item in merged["relationships"] if item["relationshipType"] == "DEPENDS_ON"
            }
            self.assertIn((purls["pkg:npm/a@1.0.0"], purls["pkg:npm/b@2.0.0"]), depends)


if __name__ == "__main__":
    unittest.main()
