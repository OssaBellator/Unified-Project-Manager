from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.doctor import diagnose


class LockfileTests(unittest.TestCase):
    def test_malformed_npm_lockfile_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{broken", encoding="utf-8")
            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            finding = next(item for item in report.findings if item.code == "lockfile.invalid")
            self.assertEqual(finding.severity, "error")

    def test_malformed_cargo_lockfile_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("[[package]\n", encoding="utf-8")
            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            self.assertIn("lockfile.invalid", {item.code for item in report.findings})

    def test_npm_root_dependency_drift_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "packageManager": "npm@11",
                "dependencies": {"react": "^19.0.0"},
            }), encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {"": {"dependencies": {"react": "^18.0.0"}}},
            }), encoding="utf-8")
            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            finding = next(item for item in report.findings if item.code == "lockfile.manifest-drift")
            self.assertIn("dependencies.react", finding.message)


if __name__ == "__main__":
    unittest.main()
