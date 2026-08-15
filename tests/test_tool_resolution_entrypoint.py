from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.tool_resolution import (
    ToolResolutionDivergence,
    ToolResolutionObservation,
    ToolResolutionReport,
)
from unified_project_manager.tool_resolution_entrypoint import main


class ToolResolutionEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"name":"app","packageManager":"pnpm@10"}', encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text('lockfileVersion: "9.0"\n', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def _report(self, *, probed: bool = False, available: bool = True) -> ToolResolutionReport:
        return ToolResolutionReport((
            ToolResolutionObservation(
                ".:node",
                "manager",
                "pnpm",
                "10",
                ("pnpm", "--version"),
                "/shims/pnpm" if available else None,
                available,
                "10.7.0" if probed and available else None,
                0 if probed and available else None,
            ),
        ), (), probed)

    def test_default_mode_requests_no_version_execution_and_reports_no_execution_guarantee(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.tool_resolution_entrypoint.collect_tool_resolution",
                return_value=self._report(probed=False),
            ) as collect:
                code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(collect.call_args.kwargs["probe_versions"])
            self.assertFalse(data["version_probes_executed"])
            self.assertEqual(data["network_guarantee"], "no-execution")
            self.assertFalse(data["network_executed"])
            self.assertIsNone(data["probe_warning"])

    def test_probe_mode_is_explicit_and_does_not_claim_offline_guarantee(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.tool_resolution_entrypoint.collect_tool_resolution",
                return_value=self._report(probed=True),
            ) as collect:
                code, data = self._json([
                    str(root), "--probe-versions", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertTrue(collect.call_args.kwargs["probe_versions"])
            self.assertTrue(data["version_probes_executed"])
            self.assertEqual(data["network_guarantee"], "not-guaranteed")
            self.assertIsNone(data["network_executed"])
            self.assertIn("cannot be guaranteed", data["probe_warning"])
            self.assertEqual(data["observations"][0]["version"], "10.7.0")

    def test_strict_fails_on_unavailable_tool_without_requiring_version_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.tool_resolution_entrypoint.collect_tool_resolution",
                return_value=self._report(available=False),
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["unavailable"], 1)
            self.assertEqual(data["summary"]["version_probe_failures"], 0)

    def test_failed_probe_only_counts_when_probes_were_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            failed = ToolResolutionReport((
                ToolResolutionObservation(
                    ".:node", "manager", "pnpm", "10", ("pnpm", "--version"),
                    "/shims/pnpm", True, "shim error", 2, "shim error\n",
                ),
            ), (), True)
            with patch(
                "unified_project_manager.tool_resolution_entrypoint.collect_tool_resolution",
                return_value=failed,
            ):
                code, data = self._json([
                    str(root), "--probe-versions", "--strict", "--json"
                ])

            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["version_probe_failures"], 1)

    def test_requirement_divergence_is_strict_failure_in_either_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            report = ToolResolutionReport(
                self._report().observations,
                (ToolResolutionDivergence("manager", "pnpm", ("9", "10"), ("a:node", "b:node")),),
                False,
            )
            with patch(
                "unified_project_manager.tool_resolution_entrypoint.collect_tool_resolution",
                return_value=report,
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["requirement_divergences"], 1)


if __name__ == "__main__":
    unittest.main()
