from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.cargo_graph import plan_cargo_graphs
from unified_project_manager.discovery import discover
from unified_project_manager.npm_graph import plan_npm_graphs
from unified_project_manager.pnpm_graph import plan_pnpm_graphs
from unified_project_manager.provider_ownership import provider_owned_component_keys


class ProviderOwnershipTests(unittest.TestCase):
    def test_scoped_npm_workspace_plan_marks_only_root_and_selected_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text(
                '{"name":"root","packageManager":"npm@11","workspaces":["packages/*"]}', encoding='utf-8'
            )
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            for name in ('a', 'b'):
                member = root / 'packages' / name
                member.mkdir(parents=True)
                (member / 'package.json').write_text(f'{{"name":"{name}"}}', encoding='utf-8')
            graph = discover(root)

            plans = plan_npm_graphs(graph, selector='a')
            owned = provider_owned_component_keys(graph, npm_plans=plans)

            self.assertEqual(owned, {'.:node', 'packages/a:node'})

    def test_unscoped_npm_workspace_plan_marks_all_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text(
                '{"name":"root","packageManager":"npm@11","workspaces":["packages/*"]}', encoding='utf-8'
            )
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            for name in ('a', 'b'):
                member = root / 'packages' / name
                member.mkdir(parents=True)
                (member / 'package.json').write_text(f'{{"name":"{name}"}}', encoding='utf-8')
            graph = discover(root)

            owned = provider_owned_component_keys(graph, npm_plans=plan_npm_graphs(graph))

            self.assertEqual(owned, {'.:node', 'packages/a:node', 'packages/b:node'})

    def test_recursive_pnpm_plan_marks_workspace_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"name":"root","packageManager":"pnpm@11"}', encoding='utf-8')
            (root / 'pnpm-workspace.yaml').write_text('packages:\n  - packages/*\n', encoding='utf-8')
            (root / 'pnpm-lock.yaml').write_text("lockfileVersion: '9.0'\n", encoding='utf-8')
            member = root / 'packages' / 'app'
            member.mkdir(parents=True)
            (member / 'package.json').write_text('{"name":"app"}', encoding='utf-8')
            graph = discover(root)

            owned = provider_owned_component_keys(graph, pnpm_plans=plan_pnpm_graphs(graph))

            self.assertEqual(owned, {'.:node', 'packages/app:node'})

    def test_cargo_workspace_plan_marks_nested_rust_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / 'member'
            member.mkdir()
            (root / 'Cargo.toml').write_text('[workspace]\nmembers=["member"]\n', encoding='utf-8')
            (root / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')
            (member / 'Cargo.toml').write_text('[package]\nname="member"\nversion="0.1.0"\n', encoding='utf-8')
            graph = discover(root)

            owned = provider_owned_component_keys(graph, cargo_plans=plan_cargo_graphs(graph))

            self.assertEqual(owned, {'.:rust', 'member:rust'})


if __name__ == '__main__':
    unittest.main()
