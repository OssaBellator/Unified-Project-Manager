from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.native_exec import NativeExecResult
from unified_project_manager.update_entrypoint import main


class UpdateEntrypointTests(unittest.TestCase):
    def _npm_project(self, root: Path) -> None:
        (root / "package.json").write_text(json.dumps({
            "name": "app",
            "packageManager": "npm@11",
            "dependencies": {"foo": "^1.0.0"},
        }), encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "app", "dependencies": {"foo": "^1.0.0"}},
                "node_modules/foo": {"version": "1.0.0"},
            },
        }), encoding="utf-8")

    def _go_project(self, root: Path) -> None:
        (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_preview_is_non_mutating_and_shows_native_side_effect_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            code, data = self._json([
                "foo", "--path", str(root), "--json"
            ])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertTrue(data["receipt_will_be_written"])
            self.assertEqual(data["plan"]["argv"], ["npm", "update", "foo"])
            self.assertEqual(data["plan"]["update_scope"], "selected")
            self.assertFalse(data["plan"]["manifest_may_change"])
            self.assertTrue(data["plan"]["native_state_may_change"])
            self.assertTrue(data["plan"]["installed_state_may_change"])
            self.assertTrue(data["plan"]["network_may_be_used"])
            self.assertFalse((root / ".upm" / "receipts").exists())

    def test_applied_update_writes_scoped_v2_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            def fake_execute(plan, _root, verify=False):
                self.assertFalse(verify)
                lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
                lock["packages"]["node_modules/foo"]["version"] = "1.1.0"
                (root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
                return NativeExecResult(plan, 0, stdout="updated\n")

            with patch(
                "unified_project_manager.update_entrypoint.execute_native_exec",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    "foo", "--path", str(root), "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertEqual(data["receipt"]["version"], 2)
            self.assertEqual(data["receipt"]["scope"], "project-native-state")
            self.assertEqual(data["receipt"]["operation"], "update")
            self.assertTrue(data["receipt"]["succeeded"])
            self.assertIsNone(data["receipt"]["verification"])
            self.assertTrue(Path(data["receipt_path"]).is_file())
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package-lock.json"], "changed")
            self.assertEqual(data["result"]["stdout"], "updated\n")

    def test_failed_update_records_partial_lock_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            def fake_execute(plan, _root, verify=False):
                lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
                lock["packages"]["node_modules/foo"]["version"] = "1.0.1-partial"
                (root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
                return NativeExecResult(plan, 5, stderr="native update failed\n")

            with patch(
                "unified_project_manager.update_entrypoint.execute_native_exec",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    "foo", "--path", str(root), "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 5)
            self.assertFalse(data["receipt"]["succeeded"])
            self.assertEqual(data["receipt"]["commands"][0]["returncode"], 5)
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package-lock.json"], "changed")
            self.assertTrue(Path(data["receipt_path"]).is_file())

    def test_go_update_without_explicit_target_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go_project(root)

            code, data = self._json(["--path", str(root), "--json"])

            self.assertEqual(code, 2)
            self.assertIn("explicit module/package targets", data["error"])
            self.assertFalse((root / ".upm").exists())

    def test_go_preview_normalizes_unversioned_target_to_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._go_project(root)

            code, data = self._json([
                "golang.org/x/text", "--path", str(root), "--json"
            ])

            self.assertEqual(code, 0)
            self.assertEqual(
                data["plan"]["argv"],
                ["go", "get", "golang.org/x/text@latest"],
            )
            self.assertTrue(data["plan"]["manifest_may_change"])
            self.assertFalse(data["plan"]["installed_state_may_change"])


if __name__ == "__main__":
    unittest.main()
