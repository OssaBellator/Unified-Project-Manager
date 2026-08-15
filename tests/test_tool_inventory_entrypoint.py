from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.tool_inventory import (
    ToolInventory,
    ToolRequirementDivergence,
    ToolResolution,
)
from unified_project_manager.tool_inventory_entrypoint import main


class ToolInventoryEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_json_inventory_is_explicitly_local_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            inventory = ToolInventory(
                resolutions=(
                    ToolResolution(
                        ".:node", "manager", "npm", "11", ("npm", "--version"),
                        "/tools/npm", True, "11.2.0", 0,
                    ),
                ),
                divergences=(),
            )

            with patch(
                "unified_project_manager.tool_inventory_entrypoint.collect_tool_inventory",
                return_value=inventory,
            ):
                code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["mutation_executed"])
            self.assertEqual(data["resolutions"][0]["resolved_path"], "/tools/npm")
            self.assertFalse(data["summary"]["strict_failed"])

    def test_strict_fails_for_missing_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            inventory = ToolInventory(
                resolutions=(
                    ToolResolution(
                        ".:node", "manager", "npm", "11", ("npm", "--version"),
                        None, False, None, None,
                    ),
                ),
                divergences=(),
            )

            with patch(
                "unified_project_manager.tool_inventory_entrypoint.collect_tool_inventory",
                return_value=inventory,
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["unavailable"], 1)
            self.assertTrue(data["summary"]["strict_failed"])

    def test_strict_fails_for_requirement_divergence_but_default_inventory_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            inventory = ToolInventory(
                resolutions=(
                    ToolResolution("a:node", "manager", "npm", "10", ("npm", "--version"), "/bin/npm", True, "11", 0),
                    ToolResolution("b:node", "manager", "npm", "11", ("npm", "--version"), "/bin/npm", True, "11", 0),
                ),
                divergences=(
                    ToolRequirementDivergence("manager", "npm", ("10", "11"), ("a:node", "b:node")),
                ),
            )

            with patch(
                "unified_project_manager.tool_inventory_entrypoint.collect_tool_inventory",
                return_value=inventory,
            ):
                default_code, default_data = self._json([str(root), "--json"])
            with patch(
                "unified_project_manager.tool_inventory_entrypoint.collect_tool_inventory",
                return_value=inventory,
            ):
                strict_code, strict_data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(default_code, 0)
            self.assertEqual(strict_code, 1)
            self.assertEqual(default_data["summary"]["requirement_divergences"], 1)
            self.assertTrue(strict_data["summary"]["strict_failed"])

    def test_failed_version_probe_is_distinct_from_unavailable_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            inventory = ToolInventory(
                resolutions=(
                    ToolResolution(
                        ".:node", "manager", "npm", "11", ("npm", "--version"),
                        "/bin/npm", True, "configuration error", 2, "configuration error\n",
                    ),
                ),
                divergences=(),
            )

            with patch(
                "unified_project_manager.tool_inventory_entrypoint.collect_tool_inventory",
                return_value=inventory,
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["unavailable"], 0)
            self.assertEqual(data["summary"]["version_probe_failures"], 1)


if __name__ == "__main__":
    unittest.main()
