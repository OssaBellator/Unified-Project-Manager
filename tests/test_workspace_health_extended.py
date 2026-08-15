from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.workspace_health_extended import all_workspace_findings


class ExtendedWorkspaceHealthTests(unittest.TestCase):
    def test_combined_health_includes_uv_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            uv = root / "uv"
            uv.mkdir()
            (uv / "pyproject.toml").write_text(
                '[project]\nname="root"\nversion="0.1.0"\n'
                '[tool.uv.workspace]\nmembers=["missing/*"]\n',
                encoding="utf-8",
            )
            (uv / "uv.lock").write_text("version=1\n", encoding="utf-8")

            findings = all_workspace_findings(discover(root))

            self.assertTrue(any(item.code == "uv.workspace.pattern-unmatched" for item in findings))


if __name__ == "__main__":
    unittest.main()
