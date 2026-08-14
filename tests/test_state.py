from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.doctor import diagnose
from unified_project_manager.state import integrity_findings, load_state, state_path, write_state


class StateTests(unittest.TestCase):
    def _node_project(self, root: Path) -> None:
        (root / "package.json").write_text('{"packageManager":"npm@11","dependencies":{"react":"^19"}}', encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")

    def test_snapshot_records_portable_manifest_and_lockfile_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            target = write_state(discover(root))
            data = load_state(root)
            self.assertEqual(target, state_path(root))
            self.assertEqual(data["version"], 1)
            self.assertEqual(set(data["files"]), {"package.json", "package-lock.json"})
            self.assertEqual(len(data["files"]["package.json"]["sha256"]), 64)

    def test_changed_tracked_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            write_state(discover(root))
            (root / "package.json").write_text('{"packageManager":"npm@11","dependencies":{"react":"^20"}}', encoding="utf-8")
            findings = integrity_findings(discover(root))
            self.assertEqual([finding.code for finding in findings], ["state.file-changed"])
            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            self.assertIn("state.file-changed", {finding.code for finding in report.findings})

    def test_missing_tracked_lockfile_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            write_state(discover(root))
            (root / "package-lock.json").unlink()
            report = diagnose(discover(root), which=lambda _name: "/bin/tool")
            codes = {finding.code for finding in report.findings}
            self.assertIn("state.file-missing", codes)
            self.assertGreaterEqual(report.errors, 1)

    def test_invalid_snapshot_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            state_path(root).parent.mkdir()
            state_path(root).write_text("not json", encoding="utf-8")
            findings = integrity_findings(discover(root))
            self.assertEqual(findings[0].code, "state.invalid")
            self.assertEqual(findings[0].severity, "error")


if __name__ == "__main__":
    unittest.main()
