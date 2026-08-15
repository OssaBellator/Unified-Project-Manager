from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.dedupe_entrypoint import main
from unified_project_manager.native_exec import NativeExecResult


class DedupeEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text(json.dumps({
            "name": "app",
            "packageManager": "npm@11",
            "dependencies": {"a": "^1.0.0", "b": "^1.0.0"},
        }), encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "app", "dependencies": {"a": "^1.0.0", "b": "^1.0.0"}},
                "node_modules/a": {"version": "1.0.0"},
                "node_modules/b": {"version": "1.0.0"},
            },
        }), encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_preview_is_non_mutating_and_states_receipt_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(data["plan"]["argv"], ["npm", "dedupe"])
            self.assertEqual(data["receipt_scope"], "project-native-state")
            self.assertIn("installed-tree", data["receipt_limit"])
            self.assertFalse((root / ".upm" / "receipts").exists())

    def test_applied_dedupe_writes_receipt_even_when_lock_bytes_do_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            def fake_execute(plan, _root, verify=False):
                self.assertFalse(verify)
                return NativeExecResult(plan, 0, stdout="deduped\n")

            with patch(
                "unified_project_manager.dedupe_entrypoint.execute_native_exec",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    str(root), "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertEqual(data["receipt"]["version"], 2)
            self.assertEqual(data["receipt"]["scope"], "project-native-state")
            self.assertEqual(data["receipt"]["operation"], "dedupe")
            self.assertEqual(data["receipt"]["commands"][0]["argv"], ["npm", "dedupe"])
            self.assertTrue(Path(data["receipt_path"]).is_file())
            self.assertTrue(all(item["status"] == "unchanged" for item in data["receipt"]["changes"]))
            self.assertIn("installed-tree", data["receipt_limit"])

    def test_failed_dedupe_records_partial_native_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            def fake_execute(plan, _root, verify=False):
                lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
                lock["packages"]["node_modules/a"]["version"] = "1.0.1-partial"
                (root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
                return NativeExecResult(plan, 4, stderr="dedupe failed\n")

            with patch(
                "unified_project_manager.dedupe_entrypoint.execute_native_exec",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    str(root), "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 4)
            self.assertFalse(data["receipt"]["succeeded"])
            self.assertEqual(data["receipt"]["commands"][0]["returncode"], 4)
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package-lock.json"], "changed")

    def test_non_node_project_is_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('version = 4\n', encoding="utf-8")

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 2)
            self.assertIn("No generic dedupe mutation", data["error"])
            self.assertFalse((root / ".upm").exists())


if __name__ == "__main__":
    unittest.main()
