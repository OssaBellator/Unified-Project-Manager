from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.storage import directory_size, project_storage, storage_summary


class StorageTests(unittest.TestCase):
    def test_directory_size_does_not_follow_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            outside = root / "outside"
            data.mkdir(); outside.mkdir()
            (data / "a.bin").write_bytes(b"a" * 10)
            (outside / "big.bin").write_bytes(b"b" * 100)
            try:
                (data / "outside-link").symlink_to(outside, target_is_directory=True)
            except OSError:
                pass
            size, files = directory_size(data)
            self.assertEqual(size, 10)
            self.assertEqual(files, 1)

    def test_hardlinked_files_are_counted_once_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "a"
            second = root / "b"
            first.write_bytes(b"x" * 32)
            try:
                os.link(first, second)
            except OSError:
                self.skipTest("hardlinks unavailable")
            size, files = directory_size(root)
            self.assertEqual(size, 32)
            self.assertEqual(files, 1)

    def test_project_storage_recognizes_ecosystem_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "frontend"; python = root / "backend"; rust = root / "engine"
            for path in (node / "node_modules", python / ".venv", rust / "target"):
                path.mkdir(parents=True)
                (path / "data.bin").write_bytes(b"1234")
            graph = ProjectGraph(root, [
                Component("node", node, "npm"),
                Component("python", python, "uv"),
                Component("rust", rust, "cargo"),
            ])
            entries = project_storage(graph)
            self.assertEqual({entry["category"] for entry in entries}, {"packages", "environment", "build"})
            summary = storage_summary(entries)
            self.assertEqual(summary["bytes"], 12)
            self.assertEqual(summary["categories"]["packages"], 4)

    def test_shared_inode_set_avoids_cross_project_hardlink_double_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"; second = root / "second"
            for project in (first, second):
                (project / "node_modules" / "pkg").mkdir(parents=True)
            source = first / "node_modules" / "pkg" / "data.bin"
            target = second / "node_modules" / "pkg" / "data.bin"
            source.write_bytes(b"x" * 64)
            try:
                os.link(source, target)
            except OSError:
                self.skipTest("hardlinks unavailable")
            seen: set[tuple[int, int]] = set()
            first_entries = project_storage(ProjectGraph(first, [Component("node", first, "npm")]), seen=seen)
            second_entries = project_storage(ProjectGraph(second, [Component("node", second, "npm")]), seen=seen)
            self.assertEqual(storage_summary(first_entries + second_entries)["bytes"], 64)


if __name__ == "__main__":
    unittest.main()
