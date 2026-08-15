from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.uv_workspace_operations import plan_uv_workspace_operations


class UvWorkspaceOperationTests(unittest.TestCase):
    def _project(self, path: Path, name: str, extra: str = "") -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\n{extra}', encoding="utf-8"
        )

    def test_install_collapses_workspace_to_one_all_packages_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            (root / "uv.lock").write_text("version=1\n", encoding="utf-8")
            self._project(root / "packages" / "a", "a")
            self._project(root / "packages" / "b", "b")

            plans, consumed = plan_uv_workspace_operations(discover(root), "install")

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].argv, ("uv", "sync", "--all-packages"))
            self.assertEqual(consumed, {".:python", "packages/a:python", "packages/b:python"})

    def test_locked_sync_uses_shared_root_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
            (root / "uv.lock").write_text("version=1\n", encoding="utf-8")
            self._project(root / "packages" / "app", "app")

            plans, _consumed = plan_uv_workspace_operations(discover(root), "sync")

            self.assertEqual(plans[0].cwd, root)
            self.assertEqual(plans[0].argv, ("uv", "sync", "--all-packages", "--locked"))

    def test_excluded_standalone_project_is_not_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(
                root,
                "root",
                '[tool.uv.workspace]\nmembers=["packages/*"]\nexclude=["packages/tool"]\n',
            )
            (root / "uv.lock").write_text("version=1\n", encoding="utf-8")
            self._project(root / "packages" / "app", "app")
            tool = root / "packages" / "tool"
            self._project(tool, "tool", '[tool.uv]\n')
            (tool / "uv.lock").write_text("version=1\n", encoding="utf-8")

            _plans, consumed = plan_uv_workspace_operations(discover(root), "install")

            self.assertIn("packages/app:python", consumed)
            self.assertNotIn("packages/tool:python", consumed)


if __name__ == "__main__":
    unittest.main()
