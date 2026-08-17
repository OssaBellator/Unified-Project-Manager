from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.node_workspace import NodeWorkspaceError, inspect_node_workspace


class NodeWorkspaceTests(unittest.TestCase):
    def test_expands_members_and_detects_unlisted_nested_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "name": "root",
                "private": True,
                "packageManager": "npm@11",
                "workspaces": ["packages/*"],
            }), encoding="utf-8")
            app = root / "packages" / "app"
            lib = root / "packages" / "lib"
            stray = root / "tools" / "stray"
            for directory in (app, lib, stray):
                directory.mkdir(parents=True)
            (app / "package.json").write_text('{"name":"app","version":"1.0.0"}', encoding="utf-8")
            (lib / "package.json").write_text('{"name":"lib","private":true}', encoding="utf-8")
            (stray / "package.json").write_text('{"name":"stray"}', encoding="utf-8")

            workspace = inspect_node_workspace(root)
            self.assertIsNotNone(workspace)
            assert workspace is not None
            self.assertEqual(workspace.manager, "npm")
            self.assertEqual([member.name for member in workspace.members], ["app", "lib"])
            unlisted = next(issue for issue in workspace.issues if issue.code == "workspace.unlisted-package")
            self.assertEqual(unlisted.path, "tools/stray")

    def test_object_packages_form_and_manager_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "packageManager": "yarn@4.0.0",
                "workspaces": {"packages": ["apps/*"]},
            }), encoding="utf-8")
            app = root / "apps" / "app"
            app.mkdir(parents=True)
            (app / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
            workspace = inspect_node_workspace(root)
            assert workspace is not None
            self.assertEqual(workspace.patterns, ("apps/*",))
            self.assertIn("workspace.manager-mismatch", {issue.code for issue in workspace.issues})

    def test_duplicate_package_names_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"workspaces":["packages/*"]}', encoding="utf-8")
            for name in ("a", "b"):
                directory = root / "packages" / name
                directory.mkdir(parents=True)
                (directory / "package.json").write_text('{"name":"same"}', encoding="utf-8")
            workspace = inspect_node_workspace(root)
            assert workspace is not None
            self.assertIn("workspace.duplicate-package-name", {issue.code for issue in workspace.issues})

    def test_unmatched_pattern_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"workspaces":["missing/*"]}', encoding="utf-8")
            workspace = inspect_node_workspace(root)
            assert workspace is not None
            self.assertIn("workspace.pattern-unmatched", {issue.code for issue in workspace.issues})

    def test_invalid_workspace_shape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"workspaces":"packages/*"}', encoding="utf-8")
            with self.assertRaisesRegex(NodeWorkspaceError, "must be an array"):
                inspect_node_workspace(root)

    def test_workspace_patterns_cannot_escape_before_member_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            outside = base / "outside"
            root.mkdir(); outside.mkdir()
            (outside / "package.json").write_text("not-json", encoding="utf-8")
            for pattern in ("../outside", outside.as_posix(), r"..\outside"):
                with self.subTest(pattern=pattern):
                    (root / "package.json").write_text(json.dumps({"workspaces": [pattern]}), encoding="utf-8")
                    with self.assertRaisesRegex(NodeWorkspaceError, "Unsafe package.json workspace pattern"):
                        inspect_node_workspace(root)

    def test_workspace_match_refuses_symlink_or_reparse_traversal_before_member_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "root"
            outside = base / "outside"
            packages = root / "packages"
            packages.mkdir(parents=True); outside.mkdir()
            (root / "package.json").write_text('{"workspaces":["packages/*"]}', encoding="utf-8")
            (outside / "package.json").write_text("not-json", encoding="utf-8")
            link = packages / "linked"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink/reparse creation unavailable: {exc}")
            with self.assertRaisesRegex(NodeWorkspaceError, "symlink or reparse point"):
                inspect_node_workspace(root)


if __name__ == "__main__":
    unittest.main()
