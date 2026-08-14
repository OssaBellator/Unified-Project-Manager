from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from unified_project_manager.cli import main


class CliTests(unittest.TestCase):
    def test_add_previews_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["add", "react", "--path", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("npm install react", output.getvalue())
            self.assertIn("Preview only", output.getvalue())

    def test_json_preview_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["sync", "--path", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(data["plans"][0]["argv"], ["cargo", "fetch", "--locked"])

    def test_ambiguous_component_is_user_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("a", "b"):
                directory = root / name
                directory.mkdir()
                (directory / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
                (directory / "package-lock.json").write_text("{}", encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                code = main(["install", "--path", str(root)])
            self.assertEqual(code, 2)
            self.assertIn("--component", error.getvalue())

    def test_sync_all_previews_every_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "frontend"
            rust = root / "engine"
            node.mkdir(); rust.mkdir()
            (node / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (node / "package-lock.json").write_text("{}", encoding="utf-8")
            (rust / "Cargo.toml").write_text('[package]\nname="engine"\nversion="0.1.0"\n', encoding="utf-8")
            (rust / "Cargo.lock").write_text("", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["sync", "--all", "--path", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual([plan["component"] for plan in data["plans"]], ["engine:rust", "frontend:node"])

    def test_snapshot_command_writes_integrity_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["snapshot", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["path"], ".upm/state.json")
            self.assertTrue((root / ".upm" / "state.json").is_file())

    def test_resolved_duplicates_human_output_uses_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/foo": {"version": "1.0.0"},
                    "node_modules/parent/node_modules/foo": {"version": "2.0.0"},
                },
            }), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["duplicates", str(root), "--resolved"])
            self.assertEqual(code, 0)
            self.assertIn("foo (multiple-resolved-versions", output.getvalue())
            self.assertIn("1.0.0 @ node_modules/foo", output.getvalue())
            self.assertIn("2.0.0 @ node_modules/parent/node_modules/foo", output.getvalue())


if __name__ == "__main__":
    unittest.main()
