from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.advisory_evidence_v2 import (
    build_advisory_evidence_v2,
    write_advisory_evidence_v2,
)
from unified_project_manager.advisory_v2_status import evaluate_advisory_v2_status
from unified_project_manager.discovery import discover
from unified_project_manager.sbom import cyclonedx_bom


class AdvisoryV2StatusTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","packageManager":"npm@11","dependencies":{"foo":"1.0.0"}}',
            encoding="utf-8",
        )
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "app", "dependencies": {"foo": "1.0.0"}},
                "node_modules/foo": {"version": "1.0.0"},
            },
        }), encoding="utf-8")

    def test_static_clean_evidence_is_current_without_network_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
                scanned_at=datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc),
            )
            write_advisory_evidence_v2(root, evidence)

            status = evaluate_advisory_v2_status(
                graph,
                now=lambda: datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(status.state, "current-clean")
            self.assertTrue(status.current)
            self.assertFalse(status.vulnerable)
            self.assertEqual(status.age_seconds, 3600)

    def test_static_inventory_change_makes_evidence_stale_not_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            write_advisory_evidence_v2(root, evidence)

            data = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
            data["packages"]["node_modules/foo"]["version"] = "2.0.0"
            (root / "package-lock.json").write_text(json.dumps(data), encoding="utf-8")

            status = evaluate_advisory_v2_status(discover(root))

            self.assertEqual(status.state, "stale-inventory")
            self.assertFalse(status.current)
            self.assertTrue(status.valid)

    def test_native_go_evidence_is_not_silently_reexecuted_for_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            graph = discover(root)
            native_bom = {
                "bomFormat": "CycloneDX",
                "specVersion": "1.7",
                "version": 1,
                "components": [
                    {"type": "library", "name": "example.com/a", "version": "v1.0.0"}
                ],
            }
            evidence = build_advisory_evidence_v2(
                native_bom,
                {"results": []},
                scanner_returncode=0,
                inventory_mode="native-go",
            )
            write_advisory_evidence_v2(root, evidence)

            status = evaluate_advisory_v2_status(graph)

            self.assertEqual(status.state, "native-inventory-unverified")
            self.assertIsNone(status.current)
            self.assertIn("does not rerun native providers", status.reason)

    def test_tampered_evidence_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            path = write_advisory_evidence_v2(root, evidence)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["summary"]["vulnerabilities"] = 1
            data["summary"]["vulnerability_ids"] = ["FAKE"]
            path.write_text(json.dumps(data), encoding="utf-8")

            status = evaluate_advisory_v2_status(graph)

            self.assertEqual(status.state, "invalid")
            self.assertFalse(status.valid)

    def test_max_age_expires_evidence_before_inventory_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
                scanned_at=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
            )
            write_advisory_evidence_v2(root, evidence)

            status = evaluate_advisory_v2_status(
                graph,
                max_age_seconds=3600,
                now=lambda: datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(status.state, "expired")
            self.assertFalse(status.current)
            self.assertEqual(status.age_seconds, 7200)


if __name__ == "__main__":
    unittest.main()
