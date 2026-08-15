from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.evidence_manifest_entrypoint import main


class EvidenceManifestEntrypointTests(unittest.TestCase):
    def _seed(self, root: Path) -> None:
        (root / ".upm" / "receipts").mkdir(parents=True)
        (root / ".upm" / "state.json").write_text('{"version":1}\n', encoding="utf-8")
        (root / ".upm" / "receipts" / "one.json").write_text('{"receipt_id":"one"}\n', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_manifest_preview_is_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._seed(root)

            code, data = self._json(["manifest", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertFalse(data["authenticated"])
            self.assertFalse(data["network_executed"])
            self.assertEqual(len(data["manifest"]["artifacts"]), 2)
            self.assertFalse((root / ".upm" / "evidence-manifest.json").exists())

    def test_apply_then_validate_then_new_evidence_invalidates_until_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._seed(root)

            apply_code, applied = self._json(["manifest", str(root), "--apply", "--json"])
            self.assertEqual(apply_code, 0)
            self.assertTrue(Path(applied["path"]).is_file())
            self.assertTrue(applied["validation"]["valid"])

            validate_code, valid = self._json(["validate", str(root), "--json"])
            self.assertEqual(validate_code, 0)
            self.assertTrue(valid["valid"])
            self.assertFalse(valid["network_executed"])
            self.assertFalse(valid["mutation_executed"])

            (root / ".upm" / "receipts" / "two.json").write_text('{"receipt_id":"two"}\n', encoding="utf-8")
            stale_code, stale = self._json(["validate", str(root), "--json"])
            self.assertEqual(stale_code, 1)
            self.assertFalse(stale["valid"])
            self.assertEqual(stale["unexpected"], [".upm/receipts/two.json"])

            rebuild_code, rebuilt = self._json(["manifest", str(root), "--apply", "--json"])
            self.assertEqual(rebuild_code, 0)
            self.assertTrue(rebuilt["validation"]["valid"])
            self.assertNotEqual(
                applied["manifest"]["evidence_set_id"],
                rebuilt["manifest"]["evidence_set_id"],
            )

    def test_validate_missing_manifest_is_nonzero_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, data = self._json(["validate", str(root), "--json"])
            self.assertEqual(code, 1)
            self.assertFalse(data["valid"])
            self.assertIn("No evidence manifest", data["reason"])
            self.assertFalse((root / ".upm").exists())


if __name__ == "__main__":
    unittest.main()
