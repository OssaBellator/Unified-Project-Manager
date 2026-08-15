from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.tool_inventory import ToolInventory, ToolResolution
from unified_project_manager.tool_state import (
    ToolStateError,
    build_tool_state,
    compare_tool_state,
    load_tool_state,
    write_tool_state,
)


class ToolStateTests(unittest.TestCase):
    def _inventory(
        self,
        *,
        path: str | None = "/usr/bin/npm",
        version: str | None = "11.0.0",
        requirement: str | None = "11",
        available: bool = True,
        returncode: int | None = 0,
        component: str = ".:node",
    ) -> ToolInventory:
        return ToolInventory((
            ToolResolution(
                component,
                "manager",
                "npm",
                requirement,
                ("npm", "--version"),
                path,
                available,
                version,
                returncode,
            ),
        ), ())

    def test_state_id_is_stable_across_generation_time(self) -> None:
        inventory = self._inventory()
        first = build_tool_state(
            inventory,
            created=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        )
        second = build_tool_state(
            inventory,
            created=datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc),
        )
        self.assertNotEqual(first.generated_at, second.generated_at)
        self.assertEqual(first.state_id, second.state_id)
        self.assertFalse(first.portable)

    def test_path_shadowing_is_reported_even_when_version_is_unchanged(self) -> None:
        baseline = build_tool_state(self._inventory(path="/usr/bin/npm"))
        status = compare_tool_state(
            baseline,
            self._inventory(path="/tmp/project-bin/npm"),
        )
        self.assertEqual(status.state, "drifted")
        self.assertEqual(len(status.changes), 1)
        change = status.changes[0]
        self.assertEqual(change.code, "tool-path-changed")
        self.assertEqual(change.before, "/usr/bin/npm")
        self.assertEqual(change.after, "/tmp/project-bin/npm")

    def test_version_and_availability_changes_are_distinct(self) -> None:
        baseline = build_tool_state(self._inventory())
        version = compare_tool_state(baseline, self._inventory(version="11.1.0"))
        unavailable = compare_tool_state(
            baseline,
            self._inventory(path=None, version=None, available=False, returncode=None),
        )
        self.assertIn("tool-version-changed", {item.code for item in version.changes})
        codes = {item.code for item in unavailable.changes}
        self.assertIn("tool-path-changed", codes)
        self.assertIn("tool-availability-changed", codes)
        self.assertIn("tool-version-changed", codes)

    def test_requirement_change_is_machine_baseline_drift_not_constraint_resolution(self) -> None:
        baseline = build_tool_state(self._inventory(requirement="10"))
        status = compare_tool_state(baseline, self._inventory(requirement="11"))
        self.assertEqual([item.code for item in status.changes], ["tool-requirement-changed"])

    def test_added_and_removed_observations_are_reported(self) -> None:
        baseline = build_tool_state(self._inventory(component="a:node"))
        added_inventory = ToolInventory(
            self._inventory(component="a:node").resolutions
            + self._inventory(component="b:node").resolutions,
            (),
        )
        added = compare_tool_state(baseline, added_inventory)
        self.assertIn("tool-observation-added", {item.code for item in added.changes})

        removed = compare_tool_state(baseline, ToolInventory((), ()))
        self.assertEqual([item.code for item in removed.changes], ["tool-observation-removed"])

    def test_absent_baseline_is_explicit(self) -> None:
        status = compare_tool_state(None, self._inventory())
        self.assertEqual(status.state, "absent")
        self.assertFalse(status.valid_baseline)
        self.assertFalse(status.current)

    def test_snapshot_round_trip_and_identity_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = build_tool_state(self._inventory())
            path = write_tool_state(root, snapshot)
            loaded = load_tool_state(root)
            self.assertEqual(loaded.state_id, snapshot.state_id)

            data = json.loads(path.read_text(encoding="utf-8"))
            data["observations"][0]["resolved_path"] = "/evil/npm"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ToolStateError, "ID"):
                load_tool_state(root)

    def test_custom_path_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            with self.assertRaisesRegex(ToolStateError, "escapes"):
                write_tool_state(
                    root,
                    build_tool_state(self._inventory()),
                    Path(outside) / "tools.json",
                )


if __name__ == "__main__":
    unittest.main()
