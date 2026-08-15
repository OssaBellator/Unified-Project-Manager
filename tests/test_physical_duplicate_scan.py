from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.physical_duplicate_scan import (
    analyze_physical_duplicates,
    discover_artifact_roots,
)


class PhysicalDuplicateScanTests(unittest.TestCase):
    def _graph(self, root: Path) -> ProjectGraph:
        return ProjectGraph(root, [Component("node", root, "npm")])

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_identical_content_on_distinct_inodes_is_observational_duplicate_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"x" * 8192
            self._write(root / "node_modules" / "a" / "payload.bin", payload)
            self._write(root / "node_modules" / "b" / "payload.bin", payload)

            report = analyze_physical_duplicates(self._graph(root), min_size_bytes=1)

            self.assertEqual(len(report.groups), 1)
            group = report.groups[0]
            self.assertEqual(group.size, len(payload))
            self.assertEqual(group.duplicate_content_bytes, len(payload))
            self.assertEqual(len(group.physical_instances), 2)
            self.assertFalse(group.reclaimable)
            self.assertEqual(report.duplicate_content_bytes, len(payload))
            self.assertEqual(report.hardlinks, ())

    def test_hardlink_aliases_are_shared_bytes_not_duplicate_physical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "node_modules" / "a" / "payload.bin"
            second = root / "node_modules" / "b" / "payload.bin"
            self._write(first, b"h" * 8192)
            second.parent.mkdir(parents=True, exist_ok=True)
            os.link(first, second)

            report = analyze_physical_duplicates(self._graph(root), min_size_bytes=1)

            self.assertEqual(report.groups, ())
            self.assertEqual(len(report.hardlinks), 1)
            hardlink = report.hardlinks[0]
            self.assertEqual(len(hardlink.paths), 2)
            self.assertTrue(hardlink.shared_physical_bytes)
            self.assertEqual(hardlink.duplicate_content_bytes, 0)
            self.assertFalse(hardlink.reclaimable)
            self.assertEqual(report.files_considered, 2)
            self.assertEqual(report.physical_files_considered, 1)

    def test_hardlink_alias_plus_separate_copy_counts_only_one_extra_physical_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"z" * 4096
            first = root / "node_modules" / "a" / "payload.bin"
            alias = root / "node_modules" / "b" / "payload.bin"
            copy = root / "node_modules" / "c" / "payload.bin"
            self._write(first, payload)
            alias.parent.mkdir(parents=True, exist_ok=True)
            os.link(first, alias)
            self._write(copy, payload)

            report = analyze_physical_duplicates(self._graph(root), min_size_bytes=1)

            self.assertEqual(len(report.groups), 1)
            self.assertEqual(len(report.groups[0].physical_instances), 2)
            aliased_instances = [
                item for item in report.groups[0].physical_instances if len(item.paths) == 2
            ]
            self.assertEqual(len(aliased_instances), 1)
            self.assertEqual(report.groups[0].duplicate_content_bytes, len(payload))
            self.assertEqual(len(report.hardlinks), 1)

    def test_file_symlink_is_not_followed_or_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temporary)
            outside = Path(outside_temp) / "secret.bin"
            outside.write_bytes(b"secret" * 2048)
            link = root / "node_modules" / "pkg" / "link.bin"
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)

            report = analyze_physical_duplicates(self._graph(root), min_size_bytes=1)

            self.assertEqual(report.files_considered, 0)
            self.assertEqual(report.bytes_hashed, 0)
            self.assertTrue(any("file symlink was not followed" in item for item in report.skipped))
            self.assertEqual(report.groups, ())

    def test_symlinked_artifact_root_is_rejected_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temporary)
            outside = Path(outside_temp) / "node_modules-real"
            outside.mkdir()
            (outside / "secret.bin").write_bytes(b"secret" * 2048)
            (root / "node_modules").symlink_to(outside, target_is_directory=True)

            roots, skipped = discover_artifact_roots(self._graph(root))
            report = analyze_physical_duplicates(self._graph(root), min_size_bytes=1)

            self.assertEqual(roots, ())
            self.assertTrue(any("artifact root is a symlink" in item for item in skipped))
            self.assertEqual(report.files_considered, 0)
            self.assertEqual(report.bytes_hashed, 0)
            self.assertEqual(report.groups, ())

    def test_minimum_size_threshold_avoids_hashing_small_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root / "node_modules" / "a" / "small.bin", b"same")
            self._write(root / "node_modules" / "b" / "small.bin", b"same")

            report = analyze_physical_duplicates(self._graph(root), min_size_bytes=4096)

            self.assertEqual(report.files_considered, 0)
            self.assertEqual(report.physical_files_considered, 0)
            self.assertEqual(report.bytes_hashed, 0)
            self.assertEqual(report.groups, ())

    def test_known_artifact_roots_cover_supported_project_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            components = [
                Component("node", root / "node", "npm"),
                Component("python", root / "python", "uv"),
                Component("rust", root / "rust", "cargo"),
                Component("go", root / "go", "go"),
            ]
            for path in (
                root / "node" / "node_modules",
                root / "python" / ".venv",
                root / "python" / "__pypackages__",
                root / "rust" / "target",
                root / "go" / "vendor",
            ):
                path.mkdir(parents=True)
            roots, skipped = discover_artifact_roots(ProjectGraph(root, components))

            self.assertEqual(skipped, ())
            self.assertEqual(
                {item.category for item in roots},
                {"node_modules", "python-environment", "cargo-target", "go-vendor"},
            )
            self.assertEqual(len(roots), 5)

    def test_negative_threshold_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "non-negative"):
                analyze_physical_duplicates(self._graph(root), min_size_bytes=-1)


if __name__ == "__main__":
    unittest.main()
