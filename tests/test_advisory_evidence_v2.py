from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.advisory_evidence_v2 import (
    build_advisory_evidence_v2,
    load_advisory_evidence_v2,
    validate_advisory_evidence_v2,
    write_advisory_evidence_v2,
)


class AdvisoryEvidenceV2Tests(unittest.TestCase):
    def _bom(self) -> dict:
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.7",
            "version": 1,
            "components": [
                {"type": "library", "name": "foo", "version": "1.0.0", "purl": "pkg:npm/foo@1.0.0"}
            ],
        }

    def _vulnerable_report(self) -> dict:
        return {
            "results": [{
                "packages": [{
                    "package": {"name": "foo", "version": "1.0.0"},
                    "vulnerabilities": [
                        {"id": "OSV-2"},
                        {"id": "OSV-1"},
                        {"id": "OSV-1"},
                    ],
                }]
            }]
        }

    def test_build_derives_summary_from_report_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = build_advisory_evidence_v2(
                self._bom(),
                self._vulnerable_report(),
                scanner_returncode=1,
                inventory_mode="static-resolved",
                scanned_at=datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc),
            )
            self.assertTrue(evidence.vulnerable)
            self.assertEqual(evidence.summary.affected_packages, 1)
            self.assertEqual(evidence.summary.vulnerabilities, 2)
            self.assertEqual(evidence.summary.vulnerability_ids, ("OSV-1", "OSV-2"))
            self.assertEqual(len(evidence.evidence_id), 64)
            self.assertEqual(len(evidence.bom_sha256), 64)
            self.assertEqual(len(evidence.report_sha256), 64)

            path = write_advisory_evidence_v2(root, evidence)
            loaded = load_advisory_evidence_v2(root, bom=self._bom())
            self.assertTrue(path.is_file())
            self.assertTrue(loaded.valid)
            self.assertEqual(loaded.evidence.evidence_id, evidence.evidence_id)

    def test_summary_tamper_is_detected_even_if_report_is_unchanged(self) -> None:
        evidence = build_advisory_evidence_v2(
            self._bom(),
            self._vulnerable_report(),
            scanner_returncode=1,
            inventory_mode="static-resolved",
        ).to_dict()
        evidence["summary"]["vulnerabilities"] = 0
        evidence["summary"]["vulnerability_ids"] = []

        validation = validate_advisory_evidence_v2(evidence, bom=self._bom())

        self.assertFalse(validation.valid)
        self.assertIn("summary", validation.reason.lower())

    def test_report_tamper_is_detected_even_if_summary_is_left_alone(self) -> None:
        evidence = build_advisory_evidence_v2(
            self._bom(),
            self._vulnerable_report(),
            scanner_returncode=1,
            inventory_mode="static-resolved",
        ).to_dict()
        evidence["report"]["results"][0]["packages"][0]["vulnerabilities"] = [{"id": "OSV-OTHER"}]

        validation = validate_advisory_evidence_v2(evidence, bom=self._bom())

        self.assertFalse(validation.valid)
        self.assertTrue(
            "summary" in validation.reason.lower()
            or "report_sha256" in validation.reason.lower()
        )

    def test_bom_mismatch_is_detected(self) -> None:
        evidence = build_advisory_evidence_v2(
            self._bom(),
            {"results": []},
            scanner_returncode=0,
            inventory_mode="static-resolved",
        ).to_dict()
        changed_bom = self._bom()
        changed_bom["components"][0]["version"] = "2.0.0"

        validation = validate_advisory_evidence_v2(evidence, bom=changed_bom)

        self.assertFalse(validation.valid)
        self.assertIn("bom", validation.reason.lower())

    def test_scanner_exit_code_and_findings_must_agree(self) -> None:
        with self.assertRaisesRegex(ValueError, "exit code 0"):
            build_advisory_evidence_v2(
                self._bom(),
                self._vulnerable_report(),
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
        with self.assertRaisesRegex(ValueError, "exit code 1"):
            build_advisory_evidence_v2(
                self._bom(),
                {"results": []},
                scanner_returncode=1,
                inventory_mode="static-resolved",
            )

    def test_path_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            evidence = build_advisory_evidence_v2(
                self._bom(),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            with self.assertRaisesRegex(ValueError, "escapes"):
                write_advisory_evidence_v2(root, evidence, Path(outside) / "evidence.json")


if __name__ == "__main__":
    unittest.main()
