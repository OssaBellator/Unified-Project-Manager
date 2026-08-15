from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.provider_registry import provider_coverage, provider_summary


class ProviderRegistryTests(unittest.TestCase):
    def test_mixed_repo_reports_capabilities_and_explicit_unsupported_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            npm = root / 'npm'; pnpm = root / 'pnpm'; uv = root / 'uv'; cargo = root / 'cargo'; yarn = root / 'yarn'; classic = root / 'classic'
            for directory in (npm, pnpm, uv, cargo, yarn, classic): directory.mkdir()
            (npm / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            (npm / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            (pnpm / 'package.json').write_text('{"packageManager":"pnpm@11"}', encoding='utf-8')
            (pnpm / 'pnpm-lock.yaml').write_text("lockfileVersion: '9.0'\n", encoding='utf-8')
            (uv / 'pyproject.toml').write_text('[project]\nname="x"\n[tool.uv]\n', encoding='utf-8')
            (uv / 'uv.lock').write_text('version=1\n', encoding='utf-8')
            (cargo / 'Cargo.toml').write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding='utf-8')
            (cargo / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')
            (yarn / 'package.json').write_text('{"packageManager":"yarn@4.6.0"}', encoding='utf-8')
            (yarn / 'yarn.lock').write_text('', encoding='utf-8')
            (classic / 'package.json').write_text('{"packageManager":"yarn@1.22.22"}', encoding='utf-8')
            (classic / 'yarn.lock').write_text('', encoding='utf-8')

            summary = provider_summary(discover(root))
            self.assertEqual(summary['total_components'], 6)
            self.assertEqual(summary['supported_components'], 5)
            self.assertEqual(set(summary['providers']), {
                'npm-lock-tree', 'pnpm-lock-tree', 'yarn-berry-resolution-graph',
                'uv-lock', 'cargo-metadata',
            })
            unsupported = [item for item in summary['coverage'] if not item['supported']]
            self.assertEqual(len(unsupported), 1)
            self.assertEqual(unsupported[0]['manager'], 'yarn')
            self.assertIn('Berry 2+', unsupported[0]['reason'])
            pnpm_coverage = next(item for item in summary['coverage'] if item['manager'] == 'pnpm')
            self.assertTrue(pnpm_coverage['provider']['supports_sbom_relationships'])
            yarn_coverage = next(
                item for item in summary['coverage']
                if item['component'] == 'yarn:node'
            )
            self.assertTrue(yarn_coverage['provider']['supports_sbom_relationships'])
            self.assertEqual(yarn_coverage['provider']['network'], 'none')
            self.assertEqual(yarn_coverage['provider']['mutation'], 'none')

    def test_pnpm_workspace_member_inherits_root_relationship_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"name":"root","packageManager":"pnpm@11"}', encoding='utf-8')
            (root / 'pnpm-workspace.yaml').write_text('packages:\n  - packages/*\n', encoding='utf-8')
            (root / 'pnpm-lock.yaml').write_text("lockfileVersion: '9.0'\n", encoding='utf-8')
            member = root / 'packages' / 'app'
            member.mkdir(parents=True)
            (member / 'package.json').write_text('{"name":"app"}', encoding='utf-8')

            coverage = {item.component: item for item in provider_coverage(discover(root))}

            self.assertTrue(coverage['.:node'].supported)
            self.assertTrue(coverage['packages/app:node'].supported)
            self.assertEqual(coverage['packages/app:node'].provider.provider, 'pnpm-lock-tree')
            self.assertTrue(coverage['packages/app:node'].provider.supports_sbom_relationships)

    def test_npm_workspace_member_inherits_root_relationship_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"name":"root","packageManager":"npm@11","workspaces":["packages/*"]}', encoding='utf-8')
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            member = root / 'packages' / 'app'
            member.mkdir(parents=True)
            (member / 'package.json').write_text('{"name":"app"}', encoding='utf-8')

            coverage = {item.component: item for item in provider_coverage(discover(root))}

            self.assertEqual(coverage['.:node'].provider.provider, 'npm-lock-tree')
            self.assertEqual(coverage['packages/app:node'].provider.provider, 'npm-lock-tree')

    def test_yarn_berry_workspace_member_inherits_isolated_root_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text(
                '{"name":"root","packageManager":"yarn@4.6.0","workspaces":["packages/*"]}',
                encoding='utf-8',
            )
            (root / 'yarn.lock').write_text('# lock\n', encoding='utf-8')
            member = root / 'packages' / 'app'
            member.mkdir(parents=True)
            (member / 'package.json').write_text('{"name":"app"}', encoding='utf-8')

            coverage = {item.component: item for item in provider_coverage(discover(root))}

            self.assertEqual(coverage['.:node'].provider.provider, 'yarn-berry-resolution-graph')
            self.assertEqual(coverage['packages/app:node'].provider.provider, 'yarn-berry-resolution-graph')
            self.assertEqual(coverage['packages/app:node'].provider.network, 'none')
            self.assertTrue(coverage['packages/app:node'].provider.supports_sbom_relationships)

    def test_cargo_workspace_member_inherits_root_relationship_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / 'member'
            member.mkdir()
            (root / 'Cargo.toml').write_text('[workspace]\nmembers=["member"]\n', encoding='utf-8')
            (root / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')
            (member / 'Cargo.toml').write_text('[package]\nname="member"\nversion="0.1.0"\n', encoding='utf-8')

            coverage = {item.component: item for item in provider_coverage(discover(root))}

            self.assertEqual(coverage['.:rust'].provider.provider, 'cargo-metadata')
            self.assertEqual(coverage['member:rust'].provider.provider, 'cargo-metadata')

    def test_network_guarantees_are_provider_specific(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('go', 'cargo'):
                (root / name).mkdir()
            (root / 'go' / 'go.mod').write_text('module example.com/app\ngo 1.24\n', encoding='utf-8')
            (root / 'cargo' / 'Cargo.toml').write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding='utf-8')
            (root / 'cargo' / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')
            coverage = provider_coverage(discover(root))
            modes = {item.ecosystem: item.provider.network for item in coverage if item.provider}
            self.assertEqual(modes['go'], 'offline')
            self.assertEqual(modes['rust'], 'offline')

    def test_missing_native_state_blocks_provider_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Cargo.toml').write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding='utf-8')
            item = provider_coverage(discover(root))[0]
            self.assertFalse(item.supported)
            self.assertIn('Cargo.lock', item.reason or '')


if __name__ == '__main__':
    unittest.main()
