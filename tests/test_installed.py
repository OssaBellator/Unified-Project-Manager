from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.doctor import diagnose


class InstalledStateTests(unittest.TestCase):
    def _write_project(self, root: Path) -> None:
        (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {},
                "node_modules/foo": {"version": "1.2.3"},
            },
        }), encoding="utf-8")

    def test_deep_doctor_detects_installed_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_project(root)
            package = root / "node_modules" / "foo"
            package.mkdir(parents=True)
            (package / "package.json").write_text('{"name":"foo","version":"9.9.9"}', encoding="utf-8")
            report = diagnose(discover(root), which=lambda _name: "/bin/tool", deep=True)
            self.assertIn("installed.version-mismatch", {finding.code for finding in report.findings})

    def test_deep_doctor_detects_missing_locked_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_project(root)
            (root / "node_modules").mkdir()
            report = diagnose(discover(root), which=lambda _name: "/bin/tool", deep=True)
            self.assertIn("installed.package-missing", {finding.code for finding in report.findings})

    def test_deep_doctor_detects_untracked_installed_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_project(root)
            foo = root / "node_modules" / "foo"
            bar = root / "node_modules" / "bar"
            foo.mkdir(parents=True)
            bar.mkdir(parents=True)
            (foo / "package.json").write_text('{"name":"foo","version":"1.2.3"}', encoding="utf-8")
            (bar / "package.json").write_text('{"name":"bar","version":"1.0.0"}', encoding="utf-8")
            report = diagnose(discover(root), which=lambda _name: "/bin/tool", deep=True)
            self.assertIn("installed.package-untracked", {finding.code for finding in report.findings})

    def test_shallow_doctor_does_not_scan_installed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_project(root)
            package = root / "node_modules" / "foo"
            package.mkdir(parents=True)
            (package / "package.json").write_text('{"name":"foo","version":"9.9.9"}', encoding="utf-8")
            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            self.assertFalse(any(finding.code.startswith("installed.") for finding in report.findings))


if __name__ == "__main__":
    unittest.main()
