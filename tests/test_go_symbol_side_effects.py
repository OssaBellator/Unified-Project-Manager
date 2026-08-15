from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_go_symbol_side_effects import (
    SideEffectSnapshotError,
    diff_named_roots,
    diff_snapshots,
    snapshot_named_roots,
    snapshot_tree,
)


class GoSymbolSideEffectSnapshotTests(unittest.TestCase):
    def test_identical_tree_has_no_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "one.txt").write_text("one\n", encoding="utf-8")

            before = snapshot_tree(root)
            after = snapshot_tree(root)
            delta = diff_snapshots(before, after)

            self.assertFalse(delta.changed)
            self.assertEqual(delta.added, ())
            self.assertEqual(delta.removed, ())
            self.assertEqual(delta.modified, ())

    def test_added_removed_and_modified_files_are_reported_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep.txt").write_text("before\n", encoding="utf-8")
            (root / "remove.txt").write_text("remove\n", encoding="utf-8")
            before = snapshot_tree(root)

            (root / "keep.txt").write_text("after\n", encoding="utf-8")
            (root / "remove.txt").unlink()
            (root / "z-added.txt").write_text("z\n", encoding="utf-8")
            (root / "a-added.txt").write_text("a\n", encoding="utf-8")
            after = snapshot_tree(root)

            delta = diff_snapshots(before, after)
            data = delta.to_dict()
            self.assertTrue(delta.changed)
            self.assertEqual([entry["path"] for entry in data["added"]], ["a-added.txt", "z-added.txt"])
            self.assertEqual([entry["path"] for entry in data["removed"]], ["remove.txt"])
            self.assertEqual([entry["path"] for entry in data["modified"]], ["keep.txt"])
            self.assertNotEqual(
                data["modified"][0]["before"]["sha256"],
                data["modified"][0]["after"]["sha256"],
            )

    def test_named_root_comparison_requires_the_same_observation_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / "one"
            two = root / "two"
            one.mkdir()
            two.mkdir()
            before = snapshot_named_roots({"project": one})
            after = snapshot_named_roots({"cache": two})

            with self.assertRaisesRegex(SideEffectSnapshotError, "different labels"):
                diff_named_roots(before, after)

    def test_different_physical_roots_cannot_be_compared_under_one_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / "one"
            two = root / "two"
            one.mkdir()
            two.mkdir()

            with self.assertRaisesRegex(SideEffectSnapshotError, "different roots"):
                diff_snapshots(snapshot_tree(one), snapshot_tree(two))


if __name__ == "__main__":
    unittest.main()
