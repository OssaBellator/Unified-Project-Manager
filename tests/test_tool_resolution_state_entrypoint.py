from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.tool_resolution import (
    ToolResolutionObservation,
    ToolResolutionReport,
)
from unified_project_manager.tool_resolution_state import (
    build_tool_resolution_state,
    write_tool_resolution_state,
)
from unified_project_manager.tool_resolution_state_entrypoint import main


class ToolResolutionStateEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","packageManager":"pnpm@10"}', encoding="utf-8"
        )
        (root / "pnpm-lock.yaml").write_text('lockfileVersion: "9.0"\n', encoding="utf-8")

    def _report(
        self,
        *,
        path: str = "/shims/pnpm",
        probes: bool = False,
        version: str | None = None,
        returncode: int | None = None,
    ) -> ToolResolutionReport:
        return ToolResolutionReport((
            ToolResolutionObservation(
                ".:node",
                "manager",
                "pnpm",
                "10",
                ("pnpm", "--version"),
                path,
                True,
                version if probes else None,
                returncode if probes else None,
            ),
        ), (), probes)

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_path_only_snapshot_preview_executes_no_probe_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution",
                return_value=self._report(probes=False),
            ) as collect:
                code, data = self._json(["snapshot", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(collect.call_args.kwargs["probe_versions"])
            self.assertFalse(data["executed"])
            self.assertFalse(data["snapshot"]["version_probes_executed"])
            self.assertEqual(data["network_guarantee"], "no-execution")
            self.assertFalse(data["network_executed"])
            self.assertFalse((root / ".upm" / "tools.json").exists())

    def test_path_only_apply_then_check_current_without_probe_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            report = self._report(probes=False)
            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution",
                return_value=report,
            ) as collect:
                apply_code, applied = self._json([
                    "snapshot", str(root), "--apply", "--json"
                ])
            self.assertEqual(apply_code, 0)
            self.assertFalse(collect.call_args.kwargs["probe_versions"])
            self.assertTrue(Path(applied["path"]).is_file())

            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution",
                return_value=report,
            ) as collect:
                check_code, checked = self._json(["check", str(root), "--json"])
            self.assertEqual(check_code, 0)
            self.assertEqual(checked["state"], "current")
            self.assertFalse(collect.call_args.kwargs["probe_versions"])
            self.assertEqual(checked["network_guarantee"], "no-execution")
            self.assertFalse(checked["network_executed"])

    def test_path_only_baseline_detects_path_shadowing_without_probe_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            baseline_report = self._report(path="/usr/bin/pnpm", probes=False)
            snapshot = build_tool_resolution_state(baseline_report)
            write_tool_resolution_state(root, snapshot)

            current_report = self._report(path="/tmp/project-bin/pnpm", probes=False)
            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution",
                return_value=current_report,
            ) as collect:
                code, data = self._json(["check", str(root), "--json"])

            self.assertEqual(code, 1)
            self.assertFalse(collect.call_args.kwargs["probe_versions"])
            self.assertEqual(data["state"], "drifted")
            self.assertEqual(
                {item["code"] for item in data["changes"]},
                {"tool-path-changed"},
            )
            self.assertEqual(data["network_guarantee"], "no-execution")

    def test_probed_snapshot_is_explicit_and_does_not_claim_offline_guarantee(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            report = self._report(
                probes=True,
                version="10.7.0",
                returncode=0,
            )
            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution",
                return_value=report,
            ) as collect:
                code, data = self._json([
                    "snapshot", str(root), "--probe-versions", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertTrue(collect.call_args.kwargs["probe_versions"])
            self.assertTrue(data["snapshot"]["version_probes_executed"])
            self.assertEqual(data["network_guarantee"], "not-guaranteed")
            self.assertIsNone(data["network_executed"])
            self.assertFalse((root / ".upm" / "tools.json").exists())

    def test_probed_baseline_check_without_flag_requires_consent_and_executes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            snapshot = build_tool_resolution_state(self._report(
                probes=True,
                version="10.7.0",
                returncode=0,
            ))
            write_tool_resolution_state(root, snapshot)

            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution"
            ) as collect:
                code, data = self._json(["check", str(root), "--json"])

            self.assertEqual(code, 1)
            collect.assert_not_called()
            self.assertEqual(data["state"], "probe-required")
            self.assertFalse(data["version_probes_executed"])
            self.assertEqual(data["network_guarantee"], "no-execution")
            self.assertFalse(data["network_executed"])

    def test_probed_baseline_check_with_flag_executes_matching_probe_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            report = self._report(probes=True, version="10.7.0", returncode=0)
            write_tool_resolution_state(root, build_tool_resolution_state(report))

            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution",
                return_value=report,
            ) as collect:
                code, data = self._json([
                    "check", str(root), "--probe-versions", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertTrue(collect.call_args.kwargs["probe_versions"])
            self.assertEqual(data["state"], "current")
            self.assertTrue(data["version_probes_executed"])
            self.assertEqual(data["network_guarantee"], "not-guaranteed")
            self.assertIsNone(data["network_executed"])

    def test_path_only_baseline_refuses_probe_mode_check_without_executing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            write_tool_resolution_state(
                root,
                build_tool_resolution_state(self._report(probes=False)),
            )

            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution"
            ) as collect:
                code, data = self._json([
                    "check", str(root), "--probe-versions", "--json"
                ])

            self.assertEqual(code, 2)
            collect.assert_not_called()
            self.assertIn("path-only", data["error"].lower())
            self.assertIn("re-snapshot", data["error"].lower())

    def test_v1_prototype_baseline_is_rejected_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            path = root / ".upm" / "tools.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "version": 1,
                "state_id": "0" * 64,
                "generated_at": "2026-08-15T00:00:00Z",
                "portable": False,
                "observations": [],
            }), encoding="utf-8")

            with patch(
                "unified_project_manager.tool_resolution_state_entrypoint.collect_tool_resolution"
            ) as collect:
                code, data = self._json(["check", str(root), "--json"])

            self.assertEqual(code, 2)
            collect.assert_not_called()
            self.assertIn("execution-safe v2", data["error"])


if __name__ == "__main__":
    unittest.main()
