from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.duplicate_classification import (
    DuplicateObservation,
    DuplicateReport,
    PackageOccurrence,
)
from unified_project_manager.duplicate_entrypoint import main


class DuplicateEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def _report(self) -> DuplicateReport:
        occurrence = PackageOccurrence(".:node", "1.0.0", "registry", "node_modules/foo")
        return DuplicateReport((
            DuplicateObservation(
                "logical-repeat",
                "node",
                "foo",
                ("1.0.0",),
                ("registry",),
                (".:node",),
                (occurrence, occurrence),
                False,
                "logical repetition is not physical reclaimability",
            ),
            DuplicateObservation(
                "version-divergence",
                "node",
                "bar",
                ("1.0.0", "2.0.0"),
                ("registry",),
                (".:node",),
                (
                    PackageOccurrence(".:node", "1.0.0", "registry", "a"),
                    PackageOccurrence(".:node", "2.0.0", "registry", "b"),
                ),
                False,
                "native constraints decide convergence",
            ),
        ), 1, 1)

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_json_keeps_categories_and_reclaimability_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.duplicate_entrypoint.classify_duplicates",
                return_value=self._report(),
            ):
                code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["logical_repeats"], 1)
            self.assertEqual(data["summary"]["version_divergences"], 1)
            self.assertEqual(data["summary"]["provenance_divergences"], 0)
            self.assertFalse(data["reclaimable"])
            self.assertFalse(data["physical_duplicate_bytes_analyzed"])
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["mutation_executed"])
            self.assertTrue(all(not item["reclaimable"] for item in data["observations"]))

    def test_strict_mode_is_a_reporting_gate_not_a_cleanup_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.duplicate_entrypoint.classify_duplicates",
                return_value=self._report(),
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 1)
            self.assertTrue(data["summary"]["strict_failed"])
            self.assertFalse((root / ".upm").exists())

    def test_empty_report_is_zero_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.duplicate_entrypoint.classify_duplicates",
                return_value=DuplicateReport((), 0, 1),
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["observations"], 0)
            self.assertEqual(data["coverage"]["components_with_resolved_inventory"], 0)
            self.assertEqual(data["coverage"]["total_components"], 1)


if __name__ == "__main__":
    unittest.main()
