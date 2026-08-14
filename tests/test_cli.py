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

    def test_resolved_why_and_graph_human_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {"": {}, "node_modules/foo": {"version": "1.2.3"}},
            }), encoding="utf-8")
            why_output = io.StringIO()
            with redirect_stdout(why_output):
                why_code = main(["why", "foo", str(root), "--resolved"])
            self.assertEqual(why_code, 0)
            self.assertIn("foo 1.2.3 @ node_modules/foo", why_output.getvalue())

            graph_output = io.StringIO()
            with redirect_stdout(graph_output):
                graph_code = main(["graph", str(root), "--resolved"])
            self.assertEqual(graph_code, 0)
            self.assertIn("foo 1.2.3 @ node_modules/foo", graph_output.getvalue())

    def test_projects_registry_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            registry = root / "registry.json"
            (project / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (project / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

            added = io.StringIO()
            with redirect_stdout(added):
                add_code = main(["projects", "add", str(project), "--registry", str(registry), "--json"])
            self.assertEqual(add_code, 0)
            self.assertTrue(json.loads(added.getvalue())["added"])

            listed = io.StringIO()
            with redirect_stdout(listed):
                list_code = main(["projects", "list", "--registry", str(registry), "--json"])
            self.assertEqual(list_code, 0)
            self.assertEqual(json.loads(listed.getvalue())["projects"], [str(project.resolve())])

            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_code = main(["projects", "status", "--registry", str(registry), "--json"])
            self.assertEqual(status_code, 0)
            self.assertEqual(json.loads(status_output.getvalue())["projects"][0]["components"], 1)

    def test_repair_previews_native_sync_for_installed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {"": {}, "node_modules/foo": {"version": "1.0.0"}},
            }), encoding="utf-8")
            package = root / "node_modules" / "foo"
            package.mkdir(parents=True)
            (package / "package.json").write_text('{"name":"foo","version":"2.0.0"}', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["repair", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("npm ci", output.getvalue())
            self.assertIn("Preview only", output.getvalue())

    def test_repair_does_not_claim_structural_corruption_is_repairable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["repair", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("No safely repairable", output.getvalue())

    def test_sbom_writes_cyclonedx_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {"": {}, "node_modules/foo": {"version": "1.0.0"}},
            }), encoding="utf-8")
            output = root / "bom.json"
            captured = io.StringIO()
            with redirect_stdout(captured):
                code = main(["sbom", str(root), "--output", str(output)])
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(data["specVersion"], "1.7")
            self.assertEqual(data["components"][0]["purl"], "pkg:npm/foo@1.0.0")
            self.assertIn(str(output), captured.getvalue())


if __name__ == "__main__":
    unittest.main()
