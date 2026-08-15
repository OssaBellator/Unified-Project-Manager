from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph, ResolvedPackage
from unified_project_manager.sbom import cyclonedx_bom, cyclonedx_bom_with_native
from unified_project_manager.sbom_consistency import compare_sboms
from unified_project_manager.sbom_project_components import (
    aggregate_project_ref,
    aggregate_spdx_id,
    project_component_ref,
    project_component_spdx_id,
)
from unified_project_manager.sbom_providers import cyclonedx_bom_with_providers
from unified_project_manager.spdx import spdx_document


class SbomProjectComponentTests(unittest.TestCase):
    def _graph(self, root: Path) -> ProjectGraph:
        return ProjectGraph(
            root=root,
            components=[
                Component(
                    ecosystem="node",
                    path=root / "web",
                    manager="npm",
                    resolved_packages=[ResolvedPackage("left-pad", "1.3.0", location="package-lock.json")],
                    metadata={"name": "web-app", "version": "1.0.0"},
                ),
                Component(
                    ecosystem="python",
                    path=root / "api",
                    manager="poetry",
                    resolved_packages=[ResolvedPackage("requests", "2.32.0", location="poetry.lock")],
                    metadata={"name": "api-service", "version": "0.2.0"},
                ),
                Component(
                    ecosystem="rust",
                    path=root / "engine",
                    manager="cargo",
                    resolved_packages=[ResolvedPackage(
                        "serde", "1.0.210", source="registry+https://github.com/rust-lang/crates.io-index", location="Cargo.lock",
                    )],
                    metadata={"name": "engine", "version": "0.3.0"},
                ),
            ],
        )

    def test_cyclonedx_has_aggregate_root_and_one_application_anchor_per_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            graph = self._graph(root)

            document = cyclonedx_bom(graph)

            aggregate = document["metadata"]["component"]
            self.assertEqual(aggregate["type"], "application")
            self.assertEqual(aggregate["bom-ref"], aggregate_project_ref(graph))

            anchors = [item for item in document["components"] if item.get("type") == "application"]
            libraries = [item for item in document["components"] if item.get("type") == "library"]
            self.assertEqual(len(anchors), 3)
            self.assertEqual(len(libraries), 3)
            self.assertEqual(
                {item["bom-ref"] for item in anchors},
                {project_component_ref(graph, component) for component in graph.components},
            )
            by_name = {item["name"]: item for item in anchors}
            self.assertEqual(by_name["web-app"]["version"], "1.0.0")
            web_properties = {item["name"]: item["value"] for item in by_name["web-app"]["properties"]}
            self.assertEqual(web_properties["upm:component-key"], "web:node")
            self.assertEqual(web_properties["upm:manager"], "npm")
            self.assertEqual(web_properties["upm:path"], "web")

            root_dependency = next(
                item for item in document["dependencies"]
                if item["ref"] == aggregate["bom-ref"]
            )
            self.assertEqual(set(root_dependency["dependsOn"]), {item["bom-ref"] for item in anchors})
            # Anchors describe topology only; static inventory does not guess
            # direct project-to-package dependency edges.
            self.assertFalse(any(item["bom-ref"] in root_dependency["dependsOn"] for item in libraries))

    def test_spdx_has_matching_application_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            graph = self._graph(root)

            document = spdx_document(
                graph,
                created=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

            applications = [
                package for package in document["packages"]
                if package.get("primaryPackagePurpose") == "APPLICATION"
            ]
            self.assertEqual(len(applications), 4)
            aggregate_id = aggregate_spdx_id(graph)
            self.assertIn(aggregate_id, {item["SPDXID"] for item in applications})
            component_ids = {project_component_spdx_id(graph, component) for component in graph.components}
            self.assertTrue(component_ids.issubset({item["SPDXID"] for item in applications}))

            contains = {
                relation["relatedSpdxElement"]
                for relation in document["relationships"]
                if relation["spdxElementId"] == aggregate_id and relation["relationshipType"] == "CONTAINS"
            }
            self.assertEqual(contains, component_ids)

    def test_anchor_identity_is_stable_across_clone_locations(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            graph_one = self._graph(Path(first) / "checkout-a")
            graph_two = self._graph(Path(second) / "checkout-b")

            self.assertEqual(aggregate_project_ref(graph_one), aggregate_project_ref(graph_two))
            self.assertEqual(
                [project_component_ref(graph_one, component) for component in graph_one.components],
                [project_component_ref(graph_two, component) for component in graph_two.components],
            )
            spdx_one = spdx_document(graph_one, created=datetime(2026, 1, 1, tzinfo=timezone.utc))
            spdx_two = spdx_document(graph_two, created=datetime(2026, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(spdx_one["documentNamespace"], spdx_two["documentNamespace"])

    def test_provider_enrichment_preserves_project_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            graph = self._graph(root)
            expected_root = aggregate_project_ref(graph)
            expected_components = {project_component_ref(graph, component) for component in graph.components}

            go_enriched = cyclonedx_bom_with_native(graph, [])
            provider_enriched = cyclonedx_bom_with_providers(
                graph,
                go_results=[],
                npm_results=[],
                cargo_results=[],
                uv_results=[],
            )
            for document in (go_enriched, provider_enriched):
                dependency = next(item for item in document["dependencies"] if item["ref"] == expected_root)
                self.assertEqual(set(dependency["dependsOn"]), expected_components)

    def test_purl_consistency_ignores_non_registry_application_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            graph = self._graph(root)

            report = compare_sboms(
                cyclonedx_bom(graph),
                spdx_document(graph, created=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            )

            self.assertTrue(report.consistent)
            self.assertEqual(report.only_cyclonedx, ())
            self.assertEqual(report.only_spdx, ())
            self.assertEqual(len(report.cyclonedx_purls), 3)
            self.assertEqual(len(report.spdx_purls), 3)


if __name__ == "__main__":
    unittest.main()
