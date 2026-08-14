from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.doctor import diagnose


class DoctorTests(unittest.TestCase):
    def test_reports_node_lockfile_conflict_and_manager_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({"packageManager": "pnpm@10"}), encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")

            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            codes = {finding.code for finding in report.findings}

            self.assertIn("lockfile.conflict", codes)
            self.assertTrue(report.errors >= 1)

    def test_reports_unavailable_manager_and_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("", encoding="utf-8")

            report = diagnose(discover(root), which=lambda _name: None)
            codes = [finding.code for finding in report.findings]

            self.assertIn("manager.unavailable", codes)
            self.assertIn("toolchain.unavailable", codes)
            self.assertEqual(report.errors, 0)
            self.assertEqual(report.warnings, 2)

    def test_invalid_manifest_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text("not = [valid", encoding="utf-8")

            report = diagnose(discover(root), which=lambda _name: "/bin/python")

            self.assertEqual(report.errors, 1)
            self.assertEqual(report.findings[0].code, "manifest.invalid")

    def test_dependency_divergence_is_informational(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, version in (("a", "^1"), ("b", "^2")):
                directory = root / name
                directory.mkdir()
                (directory / "package.json").write_text(json.dumps({"packageManager": "npm@11", "dependencies": {"zod": version}}), encoding="utf-8")
                (directory / "package-lock.json").write_text("{}", encoding="utf-8")

            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            finding = next(item for item in report.findings if item.code == "dependency.version-divergence")
            self.assertEqual(finding.severity, "info")
            self.assertEqual(report.health_score, 100)


if __name__ == "__main__":
    unittest.main()
