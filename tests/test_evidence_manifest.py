from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.evidence_manifest import (
    build_evidence_manifest,
    evidence_manifest_anchor_digest,
    load_evidence_manifest,
    validate_evidence_manifest,
    write_evidence_manifest,
)


class EvidenceManifestTests(unittest.TestCase):
    def _seed(self, root: Path) -> None:
        (root / ".upm" / "audits").mkdir(parents=True)
        (root / ".upm" / "receipts").mkdir(parents=True)
        (root / ".upm" / "state.json").write_text('{"version":1}\n', encoding="utf-8")
        (root / ".upm" / "audits" / "osv-v2.json").write_text(
            '{"version":2,"evidence_id":"x"}\n', encoding="utf-8"
        )
        (root / ".upm" / "receipts" / "a.json").write_text(
            '{"version":2,"receipt_id":"a"}\n', encoding="utf-8"
        )

    def test_evidence_set_id_is_stable_across_generation_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._seed(root)
            first = build_evidence_manifest(
                root,
                created=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
            )
            second = build_evidence_manifest(
                root,
                created=datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc),
            )
            self.assertNotEqual(first.generated_at, second.generated_at)
            self.assertEqual(first.evidence_set_id, second.evidence_set_id)
            self.assertEqual(first.artifacts, second.artifacts)
            self.assertEqual(len(evidence_manifest_anchor_digest(first)), 64)

    def test_write_and_validate_detects_changed_missing_and_unexpected_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._seed(root)
            manifest = build_evidence_manifest(root)
            path = write_evidence_manifest(root, manifest)
            self.assertTrue(path.is_file())
            self.assertTrue(load_evidence_manifest(root).valid)

            (root / ".upm" / "state.json").write_text('{"version":2}\n', encoding="utf-8")
            changed = load_evidence_manifest(root)
            self.assertFalse(changed.valid)
            self.assertEqual(changed.changed, (".upm/state.json",))

            (root / ".upm" / "state.json").unlink()
            missing = load_evidence_manifest(root)
            self.assertFalse(missing.valid)
            self.assertIn(".upm/state.json", missing.missing)

            (root / ".upm" / "state.json").write_text('{"version":1}\n', encoding="utf-8")
            (root / ".upm" / "receipts" / "b.json").write_text(
                '{"version":2,"receipt_id":"b"}\n', encoding="utf-8"
            )
            unexpected = load_evidence_manifest(root)
            self.assertFalse(unexpected.valid)
            self.assertEqual(unexpected.unexpected, (".upm/receipts/b.json",))

    def test_manifest_id_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._seed(root)
            data = build_evidence_manifest(root).to_dict()
            data["artifacts"][0]["size"] += 1
            validation = validate_evidence_manifest(root, data)
            self.assertFalse(validation.valid)
            self.assertIn("ID", validation.reason or "")

    def test_manifest_file_is_not_self_included(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._seed(root)
            first = build_evidence_manifest(root)
            write_evidence_manifest(root, first)
            second = build_evidence_manifest(root)
            self.assertEqual(first.evidence_set_id, second.evidence_set_id)
            self.assertNotIn(
                ".upm/evidence-manifest.json",
                {item.path for item in second.artifacts},
            )

    def test_custom_manifest_path_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            self._seed(root)
            manifest = build_evidence_manifest(root)
            with self.assertRaisesRegex(ValueError, "escapes"):
                write_evidence_manifest(root, manifest, Path(outside) / "manifest.json")


if __name__ == "__main__":
    unittest.main()
