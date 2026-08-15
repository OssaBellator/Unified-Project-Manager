from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.physical_duplicate_entrypoint import main


class PhysicalDuplicateEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_duplicate_content_is_reported_but_not_reclaimable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            payload = b"same" * 2048
            for name in ("a", "b"):
                path = root / "node_modules" / name / "payload.bin"
                path.parent.mkdir(parents=True)
                path.write_bytes(payload)

            code, data = self._json([
                str(root), "--min-size-bytes", "1", "--json"
            ])

            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["groups"], 1)
            self.assertEqual(data["summary"]["duplicate_content_bytes"], len(payload))
            self.assertFalse(data["reclaimable"])
            self.assertFalse(data["groups"][0]["reclaimable"])
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["mutation_executed"])

    def test_strict_reports_duplicate_content_without_mutating_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            payload = b"duplicate" * 1024
            first = root / "node_modules" / "a" / "payload.bin"
            second = root / "node_modules" / "b" / "payload.bin"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(payload)
            second.write_bytes(payload)

            code, data = self._json([
                str(root), "--min-size-bytes", "1", "--strict", "--json"
            ])

            self.assertEqual(code, 1)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertEqual(first.read_bytes(), payload)
            self.assertEqual(second.read_bytes(), payload)
            self.assertEqual(data["summary"]["groups"], 1)

    def test_hardlinks_do_not_fail_strict_physical_duplicate_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            first = root / "node_modules" / "a" / "payload.bin"
            second = root / "node_modules" / "b" / "payload.bin"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"hardlinked" * 1024)
            os.link(first, second)

            code, data = self._json([
                str(root), "--min-size-bytes", "1", "--strict", "--json"
            ])

            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["groups"], 0)
            self.assertEqual(data["summary"]["hardlink_groups"], 1)
            self.assertEqual(data["summary"]["duplicate_content_bytes"], 0)

    def test_default_threshold_is_visible_and_skips_small_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            for name in ("a", "b"):
                path = root / "node_modules" / name / "tiny"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"x")

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["min_size_bytes"], 4096)
            self.assertEqual(data["summary"]["files_considered"], 0)
            self.assertEqual(data["summary"]["bytes_hashed"], 0)

    def test_negative_threshold_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            code, data = self._json([
                str(root), "--min-size-bytes", "-1", "--json"
            ])
            self.assertEqual(code, 2)
            self.assertIn("non-negative", data["error"])


if __name__ == "__main__":
    unittest.main()
