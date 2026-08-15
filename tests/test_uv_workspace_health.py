from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.uv_workspace_health import uv_workspace_findings


class UvWorkspaceHealthTests(unittest.TestCase):
    def _project(self, path: Path, name: str, extra: str = "") -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\n{extra}', encoding="utf-8"
        )

    def test_missing_shared_lock_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            self._project(root / "packages" / "app", "app")

            findings = uv_workspace_findings(discover(root))

            codes = {item.code for item in findings}
            self.assertIn("uv.workspace.lock-missing", codes)

    def test_stale_member_pattern_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["missing/*"]\n')
            (root / "uv.lock").write_text("version=1\n", encoding="utf-8")

            finding = next(
                item for item in uv_workspace_findings(discover(root))
                if item.code == "uv.workspace.pattern-unmatched"
            )

            self.assertEqual(finding.severity, "warning")

    def test_nested_workspace_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            (root / "uv.lock").write_text("version=1\n", encoding="utf-8")
            nested = root / "packages" / "nested"
            self._project(nested, "nested", '[tool.uv.workspace]\nmembers=[]\n')
            (nested / "uv.lock").write_text("version=1\n", encoding="utf-8")

            findings = uv_workspace_findings(discover(root))

            self.assertTrue(any(item.severity == "error" and "Nested uv workspace" in item.message for item in findings))


if __name__ == "__main__":
    unittest.main()
