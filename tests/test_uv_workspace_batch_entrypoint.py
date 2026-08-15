from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.root_entrypoint import main


class UvWorkspaceBatchEntrypointTests(unittest.TestCase):
    def _workspace(self, root: Path) -> None:
        (root / "pyproject.toml").write_text(
            '[project]\nname="root"\nversion="0.1.0"\n'
            '[tool.uv.workspace]\nmembers=["packages/*"]\n',
            encoding="utf-8",
        )
        (root / "uv.lock").write_text("version=1\n", encoding="utf-8")
        for name in ("a", "b"):
            member = root / "packages" / name
            member.mkdir(parents=True)
            (member / "pyproject.toml").write_text(
                f'[project]\nname="{name}"\nversion="0.1.0"\n', encoding="utf-8"
            )

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_install_all_collapses_uv_workspace_to_one_root_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)

            code, data = self._json(["install", "--all", "--path", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(len(data["plans"]), 1)
            self.assertEqual(data["plans"][0]["manager"], "uv")
            self.assertEqual(data["plans"][0]["argv"], ["uv", "sync", "--all-packages"])
            workspace = next(item for item in data["workspace_batch"]["workspace_plans"] if item["workspace_kind"] == "uv")
            self.assertEqual(set(workspace["member_components"]), {"packages/a:python", "packages/b:python"})
            self.assertEqual(set(data["workspace_batch"]["consumed_components"]), {".:python", "packages/a:python", "packages/b:python"})

    def test_sync_all_uses_locked_uv_workspace_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)

            code, data = self._json(["sync", "--all", "--path", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["plans"][0]["argv"], ["uv", "sync", "--all-packages", "--locked"])


if __name__ == "__main__":
    unittest.main()
