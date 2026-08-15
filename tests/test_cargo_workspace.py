from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.cargo_graph import cargo_provider_component_keys, plan_cargo_graphs
from unified_project_manager.cargo_workspace import cargo_workspace_ownership, inspect_cargo_workspace
from unified_project_manager.discovery import discover


class CargoWorkspaceTests(unittest.TestCase):
    def test_explicit_member_and_unrelated_nested_project_have_separate_graph_owners(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "member"
            unrelated = root / "tools" / "unrelated"
            member.mkdir()
            unrelated.mkdir(parents=True)
            (root / "Cargo.toml").write_text('[workspace]\nmembers=["member"]\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            (member / "Cargo.toml").write_text('[package]\nname="member"\nversion="0.1.0"\n', encoding="utf-8")
            (unrelated / "Cargo.toml").write_text('[package]\nname="unrelated"\nversion="0.1.0"\n', encoding="utf-8")
            (unrelated / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            graph = discover(root)

            plans = plan_cargo_graphs(graph)

            self.assertEqual({plan.cwd for plan in plans}, {root, unrelated})
            ownership = cargo_provider_component_keys(graph, plans)
            self.assertIn("member:rust", ownership)
            self.assertIn("tools/unrelated:rust", ownership)

    def test_exclude_removes_glob_match_from_workspace_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "crates" / "app"
            tool = root / "crates" / "tool"
            app.mkdir(parents=True); tool.mkdir(parents=True)
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers=["crates/*"]\nexclude=["crates/tool"]\n', encoding="utf-8"
            )
            (root / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            (app / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            (tool / "Cargo.toml").write_text('[package]\nname="tool"\nversion="0.1.0"\n', encoding="utf-8")
            (tool / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            graph = discover(root)
            roots, owners = cargo_workspace_ownership(graph)

            self.assertIn(app.resolve(), owners)
            self.assertNotIn(tool.resolve(), owners)
            self.assertEqual({plan.cwd for plan in plan_cargo_graphs(graph)}, {root, tool})
            self.assertIn("crates/tool", next(iter(roots.values())).exclude)

    def test_in_root_path_dependency_is_added_transitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            util = root / "util"
            app.mkdir(); util.mkdir()
            (root / "Cargo.toml").write_text('[workspace]\nmembers=["app"]\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            (app / "Cargo.toml").write_text(
                '[package]\nname="app"\nversion="0.1.0"\n[dependencies]\nutil={path="../util"}\n',
                encoding="utf-8",
            )
            (util / "Cargo.toml").write_text('[package]\nname="util"\nversion="0.1.0"\n', encoding="utf-8")
            graph = discover(root)
            root_component = next(component for component in graph.components if component.path == root)
            model = inspect_cargo_workspace(graph, root_component)
            assert model is not None

            self.assertEqual(set(model.members), {"app:rust", "util:rust"})
            self.assertEqual(plan_cargo_graphs(graph, selector="util")[0].cwd, root)

    def test_package_workspace_pointer_claims_discovered_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "member"
            member.mkdir()
            (root / "Cargo.toml").write_text('[workspace]\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            (member / "Cargo.toml").write_text(
                '[package]\nname="member"\nversion="0.1.0"\nworkspace=".."\n', encoding="utf-8"
            )
            graph = discover(root)
            _roots, owners = cargo_workspace_ownership(graph)

            self.assertIn(member.resolve(), owners)
            self.assertEqual(plan_cargo_graphs(graph, selector="member")[0].cwd, root)

    def test_unmatched_member_pattern_is_preserved_as_workspace_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[workspace]\nmembers=["missing/*"]\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version=4\n", encoding="utf-8")
            graph = discover(root)
            root_component = graph.components[0]
            model = inspect_cargo_workspace(graph, root_component)
            assert model is not None
            self.assertEqual(model.unmatched_member_patterns, ("missing/*",))


if __name__ == "__main__":
    unittest.main()
