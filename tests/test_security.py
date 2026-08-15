from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main
from unified_project_manager.native_graph import NativeGraphPlan, NativeGraphResult, NativeModule
from unified_project_manager.security import execute_security_scan, plan_security_scan


class SecurityTests(unittest.TestCase):
    def _npm_project(self, root: Path) -> None:
        (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "app", "version": "1.0.0"},
                "node_modules/foo": {"version": "1.2.3"},
            },
        }), encoding="utf-8")

    def test_plan_is_local_and_does_not_require_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            plan = plan_security_scan(discover(root))
            self.assertEqual(plan.package_count, 1)
            self.assertTrue(plan.package_count_exact)
            self.assertTrue(plan.to_dict()["network_may_be_used"])
            self.assertIn("<temporary-bom.cdx.json>", plan.argv_template)

    def test_native_go_preview_does_not_execute_go(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            with patch("unified_project_manager.security.execute_native_graph_offline") as execute:
                plan = plan_security_scan(discover(root), native_go=True)
            execute.assert_not_called()
            self.assertFalse(plan.package_count_exact)
            self.assertEqual(plan.package_count, 0)

    def test_execute_uses_temporary_cyclonedx_and_exact_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            graph = discover(root)
            plan = plan_security_scan(graph)
            observed_sbom = None

            def run(argv, **kwargs):
                nonlocal observed_sbom
                observed_sbom = Path(argv[-1])
                self.assertTrue(observed_sbom.is_file())
                self.assertTrue(observed_sbom.name.endswith(".cdx.json"))
                data = json.loads(observed_sbom.read_text(encoding="utf-8"))
                self.assertEqual(data["components"][0]["purl"], "pkg:npm/foo@1.2.3")
                self.assertEqual(argv[0], "/tools/osv-scanner")
                return subprocess.CompletedProcess(argv, 0, '{"results":[]}', "")

            result = execute_security_scan(graph, plan, run=run, which=lambda _name: "/tools/osv-scanner")
            self.assertTrue(result.scanner_succeeded)
            self.assertFalse(result.vulnerable)
            self.assertIsNotNone(result.bom)
            assert observed_sbom is not None
            self.assertFalse(observed_sbom.exists())

    def test_osv_exit_one_is_findings_not_scanner_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            graph = discover(root)
            report = {
                "results": [{
                    "packages": [{
                        "package": {"name": "foo", "version": "1.2.3", "ecosystem": "npm"},
                        "vulnerabilities": [
                            {"id": "GHSA-test-1"},
                            {"id": "CVE-test-2"},
                        ],
                    }],
                }],
            }

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 1, json.dumps(report), "")

            result = execute_security_scan(
                graph,
                plan_security_scan(graph),
                run=run,
                which=lambda _name: "/tools/osv-scanner",
            )
            self.assertTrue(result.scanner_succeeded)
            self.assertTrue(result.vulnerable)
            self.assertEqual(result.summary, {"affected_packages": 1, "vulnerabilities": 2})
            self.assertIsNotNone(result.bom)

    def test_cli_is_preview_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            output = io.StringIO()
            with patch("unified_project_manager.security_entrypoint.execute_security_scan") as execute, redirect_stdout(output):
                code = main(["audit", str(root), "--json"])
            execute.assert_not_called()
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertTrue(data["plan"]["network_may_be_used"])

    def test_native_go_apply_can_enrich_temporary_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            graph = discover(root)
            plan = plan_security_scan(graph, native_go=True)
            native_plan = NativeGraphPlan(".:go", "go", "go", root, ("go",), ("go",))
            native_result = NativeGraphResult(native_plan, [
                NativeModule(".:go", "example.com/app", None, main=True),
                NativeModule(".:go", "golang.org/x/text", "v0.22.0"),
            ], [], 0)

            def scan(argv, **kwargs):
                bom = json.loads(Path(argv[-1]).read_text(encoding="utf-8"))
                self.assertIn("pkg:golang/golang.org/x/text@v0.22.0", {item.get("purl") for item in bom["components"]})
                return subprocess.CompletedProcess(argv, 0, '{"results":[]}', "")

            result = execute_security_scan(
                graph,
                plan,
                run=scan,
                which=lambda _name: "/tools/osv-scanner",
                execute_go=lambda _plan: native_result,
            )
            self.assertTrue(result.scanner_succeeded)
            self.assertIsNotNone(result.bom)


if __name__ == "__main__":
    unittest.main()
