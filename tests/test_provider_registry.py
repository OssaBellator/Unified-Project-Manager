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
            npm = root / 'npm'; uv = root / 'uv'; cargo = root / 'cargo'; yarn = root / 'yarn'
            for directory in (npm, uv, cargo, yarn): directory.mkdir()
            (npm / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            (npm / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            (uv / 'pyproject.toml').write_text('[project]\nname="x"\n[tool.uv]\n', encoding='utf-8')
            (uv / 'uv.lock').write_text('version=1\n', encoding='utf-8')
            (cargo / 'Cargo.toml').write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding='utf-8')
            (cargo / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')
            (yarn / 'package.json').write_text('{"packageManager":"yarn@4"}', encoding='utf-8')
            (yarn / 'yarn.lock').write_text('', encoding='utf-8')

            summary = provider_summary(discover(root))
            self.assertEqual(summary['total_components'], 4)
            self.assertEqual(summary['supported_components'], 3)
            self.assertEqual(set(summary['providers']), {'npm-lock-tree', 'uv-lock', 'cargo-metadata'})
            unsupported = [item for item in summary['coverage'] if not item['supported']]
            self.assertEqual(unsupported[0]['manager'], 'yarn')

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
            self.assertEqual(modes['go'], 'may-use-network')
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
