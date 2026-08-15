from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.duplicate_classification import classify_duplicates
from unified_project_manager.models import Component, ProjectGraph, ResolvedPackage


class DuplicateClassificationTests(unittest.TestCase):
    def test_logical_version_and_provenance_categories_can_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "node",
                    root / "frontend",
                    "npm",
                    resolved_packages=[
                        ResolvedPackage("foo", "1.0.0", "https://registry-a/foo.tgz", "node_modules/foo"),
                        ResolvedPackage("foo", "1.0.0", "https://registry-a/foo.tgz", "node_modules/a/node_modules/foo"),
                        ResolvedPackage("foo", "1.0.0", "https://registry-b/foo.tgz", "node_modules/b/node_modules/foo"),
                        ResolvedPackage("foo", "2.0.0", "https://registry-a/foo-2.tgz", "node_modules/c/node_modules/foo"),
                        ResolvedPackage("bar", "1.0.0", "https://registry-a/bar.tgz", "node_modules/bar"),
                    ],
                ),
            ])

            report = classify_duplicates(graph)
            foo = [item for item in report.observations if item.name == "foo"]

            self.assertEqual(
                [item.category for item in foo],
                ["logical-repeat", "version-divergence", "provenance-divergence"],
            )
            logical, versions, provenance = foo
            self.assertEqual(len(logical.occurrences), 2)
            self.assertEqual(logical.versions, ("1.0.0",))
            self.assertEqual(versions.versions, ("1.0.0", "2.0.0"))
            self.assertEqual(provenance.versions, ("1.0.0",))
            self.assertEqual(
                provenance.sources,
                ("https://registry-a/foo.tgz", "https://registry-b/foo.tgz"),
            )
            self.assertTrue(all(not item.reclaimable for item in foo))
            self.assertNotIn("bar", {item.name for item in report.observations})

    def test_same_identity_across_components_is_logical_repeat_not_physical_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "rust",
                    root / "a",
                    "cargo",
                    resolved_packages=[ResolvedPackage("serde", "1.0.220", "registry+crates.io", "Cargo.lock")],
                ),
                Component(
                    "rust",
                    root / "b",
                    "cargo",
                    resolved_packages=[ResolvedPackage("serde", "1.0.220", "registry+crates.io", "Cargo.lock")],
                ),
            ])

            report = classify_duplicates(graph)

            self.assertEqual(len(report.observations), 1)
            observation = report.observations[0]
            self.assertEqual(observation.category, "logical-repeat")
            self.assertEqual(observation.components, ("a:rust", "b:rust"))
            self.assertFalse(observation.reclaimable)
            self.assertIn("does not prove duplicate physical bytes", observation.rationale)

    def test_version_divergence_without_repeat_is_not_mislabeled_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "python",
                    root,
                    "uv",
                    resolved_packages=[
                        ResolvedPackage("urllib3", "1.26.20", "registry", None),
                        ResolvedPackage("urllib3", "2.5.0", "registry", None),
                    ],
                ),
            ])

            report = classify_duplicates(graph)

            self.assertEqual([item.category for item in report.observations], ["version-divergence"])

    def test_provenance_divergence_requires_same_version_with_multiple_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "python",
                    root,
                    "uv",
                    resolved_packages=[
                        ResolvedPackage("demo", "1.0.0", "registry:https://a", None),
                        ResolvedPackage("demo", "1.0.0", "git:https://example/repo", None),
                    ],
                ),
            ])

            report = classify_duplicates(graph)

            categories = {item.category for item in report.observations}
            self.assertEqual(categories, {"provenance-divergence"})
            observation = report.observations[0]
            self.assertEqual(observation.versions, ("1.0.0",))
            self.assertFalse(observation.reclaimable)

    def test_coverage_does_not_pretend_empty_inventory_was_analyzed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("go", root / "go", "go", resolved_packages=[]),
                Component(
                    "node",
                    root / "node",
                    "npm",
                    resolved_packages=[ResolvedPackage("a", "1.0.0", "registry", None)],
                ),
            ])

            report = classify_duplicates(graph)

            self.assertEqual(report.components_with_resolved_inventory, 1)
            self.assertEqual(report.total_components, 2)
            self.assertEqual(report.observations, ())
            self.assertFalse(report.to_dict()["physical_duplicate_bytes_analyzed"])


if __name__ == "__main__":
    unittest.main()
