from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.tool_resolution import (
    ToolResolutionObservation,
    ToolResolutionReport,
)
from unified_project_manager.tool_resolution_state import (
    ToolResolutionStateError,
    build_tool_resolution_state,
    compare_tool_resolution_state,
    load_tool_resolution_state,
    write_tool_resolution_state,
)


class ToolResolutionStateTests(unittest.TestCase):
    def _report(
        self,
        *,
        path: str | None = "/usr/bin/npm",
        version: str | None = None,
        returncode: int | None = None,
        probes: bool = False,
        requirement: str | None = "11",
    ) -> ToolResolutionReport:
        return ToolResolutionReport((
            ToolResolutionObservation(
                ".:node",
                "manager",
                "npm",
                requirement,
                ("npm", "--version"),
                path,
                path is not None,
                version if probes else None,
                returncode if probes else None,
            ),
        ), (), probes)

    def test_state_identity_binds_probe_mode(self) -> None:
        path_only = build_tool_resolution_state(
            self._report(probes=False),
            created=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        )
        probed = build_tool_resolution_state(
            self._report(probes=True, version="11.0.0", returncode=0),
            created=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(path_only.version_probes_executed)
        self.assertTrue(probed.version_probes_executed)
        self.assertNotEqual(path_only.state_id, probed.state_id)

    def test_generation_time_does_not_change_same_mode_state_id(self) -> None:
        first = build_tool_resolution_state(
            self._report(),
            created=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        )
        second = build_tool_resolution_state(
            self._report(),
            created=datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc),
        )
        self.assertNotEqual(first.generated_at, second.generated_at)
        self.assertEqual(first.state_id, second.state_id)

    def test_path_only_baseline_detects_path_requirement_and_availability_drift(self) -> None:
        baseline = build_tool_resolution_state(self._report(path="/usr/bin/npm", requirement="11"))
        path_drift = compare_tool_resolution_state(
            baseline,
            self._report(path="/tmp/npm", requirement="11"),
        )
        requirement_drift = compare_tool_resolution_state(
            baseline,
            self._report(path="/usr/bin/npm", requirement="12"),
        )
        unavailable = compare_tool_resolution_state(
            baseline,
            self._report(path=None, requirement="11"),
        )
        self.assertEqual({item.code for item in path_drift.changes}, {"tool-path-changed"})
        self.assertEqual({item.code for item in requirement_drift.changes}, {"tool-requirement-changed"})
        self.assertEqual(
            {item.code for item in unavailable.changes},
            {"tool-path-changed", "tool-availability-changed"},
        )

    def test_probed_baseline_detects_version_and_probe_returncode_drift(self) -> None:
        baseline = build_tool_resolution_state(
            self._report(probes=True, version="11.0.0", returncode=0)
        )
        status = compare_tool_resolution_state(
            baseline,
            self._report(probes=True, version="11.1.0", returncode=2),
        )
        self.assertEqual(
            {item.code for item in status.changes},
            {"tool-version-changed", "tool-version-probe-changed"},
        )

    def test_probe_mode_mismatch_is_not_compared_as_drift(self) -> None:
        path_only = build_tool_resolution_state(self._report(probes=False))
        probed_report = self._report(probes=True, version="11.0.0", returncode=0)
        status = compare_tool_resolution_state(path_only, probed_report)
        self.assertEqual(status.state, "mode-mismatch")
        self.assertEqual(status.changes, ())

    def test_missing_current_report_for_probed_baseline_is_probe_required(self) -> None:
        baseline = build_tool_resolution_state(
            self._report(probes=True, version="11.0.0", returncode=0)
        )
        status = compare_tool_resolution_state(baseline, None)
        self.assertEqual(status.state, "probe-required")
        self.assertIn("--probe-versions", status.reason)

    def test_path_only_state_rejects_embedded_version_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = build_tool_resolution_state(self._report(probes=False))
            path = write_tool_resolution_state(root, snapshot)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["observations"][0]["version"] = "11.0.0"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ToolResolutionStateError, "Path-only"):
                load_tool_resolution_state(root)

    def test_state_identity_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = build_tool_resolution_state(self._report())
            path = write_tool_resolution_state(root, snapshot)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["observations"][0]["resolved_path"] = "/evil/npm"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ToolResolutionStateError, "ID"):
                load_tool_resolution_state(root)

    def test_v1_prototype_baseline_is_rejected_with_resnapshot_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / ".upm" / "tools.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "version": 1,
                "state_id": "0" * 64,
                "generated_at": "2026-08-15T00:00:00Z",
                "portable": False,
                "observations": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ToolResolutionStateError, "execution-safe v2"):
                load_tool_resolution_state(root)


if __name__ == "__main__":
    unittest.main()
