from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.tool_inventory import ToolInventory, ToolResolution
from unified_project_manager.tool_state_entrypoint import main


class ToolStateEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def _inventory(self, path: str = "/usr/bin/npm", version: str = "11.0.0") -> ToolInventory:
        return ToolInventory((
            ToolResolution(
                ".:node", "manager", "npm", "11", ("npm", "--version"),
                path, True, version, 0,
            ),
        ), ())

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_snapshot_is_preview_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.tool_state_entrypoint.collect_tool_inventory",
                return_value=self._inventory(),
            ):
                code, data = self._json(["snapshot", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertFalse(data["snapshot"]["portable"])
            self.assertFalse(data["network_executed"])
            self.assertEqual(data["snapshot"]["observations"][0]["resolved_path"], "/usr/bin/npm")
            self.assertFalse((root / ".upm" / "tools.json").exists())

    def test_apply_then_check_current_then_detect_path_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            with patch(
                "unified_project_manager.tool_state_entrypoint.collect_tool_inventory",
                return_value=self._inventory("/usr/bin/npm"),
            ):
                apply_code, applied = self._json([
                    "snapshot", str(root), "--apply", "--json"
                ])
            self.assertEqual(apply_code, 0)
            self.assertTrue(Path(applied["path"]).is_file())
            self.assertFalse(applied["snapshot"]["portable"])

            with patch(
                "unified_project_manager.tool_state_entrypoint.collect_tool_inventory",
                return_value=self._inventory("/usr/bin/npm"),
            ):
                current_code, current = self._json(["check", str(root), "--json"])
            self.assertEqual(current_code, 0)
            self.assertEqual(current["state"], "current")
            self.assertFalse(current["network_executed"])
            self.assertFalse(current["mutation_executed"])

            with patch(
                "unified_project_manager.tool_state_entrypoint.collect_tool_inventory",
                return_value=self._inventory("/tmp/project-bin/npm"),
            ):
                drift_code, drift = self._json(["check", str(root), "--json"])
            self.assertEqual(drift_code, 1)
            self.assertEqual(drift["state"], "drifted")
            codes = {item["code"] for item in drift["changes"]}
            self.assertEqual(codes, {"tool-path-changed"})

    def test_check_without_baseline_is_nonzero_but_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.tool_state_entrypoint.collect_tool_inventory",
                return_value=self._inventory(),
            ):
                code, data = self._json(["check", str(root), "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(data["state"], "absent")
            self.assertFalse((root / ".upm").exists())

    def test_corrupt_baseline_is_command_error_not_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            state = root / ".upm" / "tools.json"
            state.parent.mkdir(parents=True)
            state.write_text('{"version":1,"state_id":"bad"}', encoding="utf-8")
            with patch(
                "unified_project_manager.tool_state_entrypoint.collect_tool_inventory",
                return_value=self._inventory(),
            ):
                code, data = self._json(["check", str(root), "--json"])

            self.assertEqual(code, 2)
            self.assertIn("tool state", data["error"].lower())


if __name__ == "__main__":
    unittest.main()
