from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.native_cyclonedx import NativeCycloneDxError, build_native_cyclonedx
from unified_project_manager.npm_sbom import NpmSbomResult
from unified_project_manager.pnpm_sbom import PnpmSbomResult


class NativeCycloneDxTests(unittest.TestCase):
    def test_mixed_npm_pnpm_inventory_uses_native_lockfile_sboms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            npm = root / "npm"
            pnpm = root / "pnpm"
            npm.mkdir(); pnpm.mkdir()
            (npm / "package.json").write_text('{"name":"npm-app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (npm / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            (pnpm / "package.json").write_text('{"name":"pnpm-app","version":"1.0.0","packageManager":"pnpm@11"}', encoding="utf-8")
            (pnpm / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            graph = discover(root)

            def execute_npm(plan):
                purl = "pkg:npm/npm-dep@1.2.3"
                document = {
                    "bomFormat":"CycloneDX","specVersion":"1.5","version":1,
                    "metadata":{"component":{"type":"application","name":"npm-app","version":"1.0.0","bom-ref":"npm-root"}},
                    "components":[{"type":"library","name":"npm-dep","version":"1.2.3","bom-ref":purl,"purl":purl}],
                    "dependencies":[{"ref":"npm-root","dependsOn":[purl]}],
                }
                return NpmSbomResult(plan, document, 0)

            def execute_pnpm(plan):
                purl = "pkg:npm/pnpm-dep@4.5.6?repository_url=https%3A%2F%2Fnpm.example%2F"
                document = {
                    "bomFormat":"CycloneDX","specVersion":"1.7","version":1,
                    "metadata":{"component":{"type":"application","name":"pnpm-app","version":"1.0.0","bom-ref":"pnpm-root"}},
                    "components":[{"type":"library","name":"pnpm-dep","version":"4.5.6","bom-ref":purl,"purl":purl}],
                    "dependencies":[{"ref":"pnpm-root","dependsOn":[purl]}],
                }
                return PnpmSbomResult(plan, [document], 0)

            inventory = build_native_cyclonedx(
                graph,
                execute_npm=execute_npm,
                execute_pnpm=execute_pnpm,
            )

            self.assertEqual(inventory.bom["specVersion"], "1.7")
            purls = {item.get("purl") for item in inventory.bom["components"]}
            self.assertIn("pkg:npm/npm-dep@1.2.3", purls)
            self.assertIn(
                "pkg:npm/pnpm-dep@4.5.6?repository_url=https%3A%2F%2Fnpm.example%2F",
                purls,
            )
            self.assertEqual(inventory.provider_counts()["npm-native-sbom"], 1)
            self.assertEqual(inventory.provider_counts()["pnpm-native-sbom"], 1)

    def test_requested_provider_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            graph = discover(root)

            def execute_npm(plan):
                return NpmSbomResult(plan, None, 2, "native sbom failed")

            with self.assertRaisesRegex(NativeCycloneDxError, "native sbom failed"):
                build_native_cyclonedx(graph, execute_npm=execute_npm)


if __name__ == "__main__":
    unittest.main()
