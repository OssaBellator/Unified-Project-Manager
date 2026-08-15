from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.npm_graph import NpmGraphPlan, NpmGraphResult, parse_npm_ls
from unified_project_manager.sbom_consistency import compare_sboms
from unified_project_manager.sbom_providers import cyclonedx_bom_with_providers
from unified_project_manager.spdx import spdx_document


class SbomConsistencyTests(unittest.TestCase):
    def test_same_static_inventory_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            (root / 'package-lock.json').write_text(json.dumps({
                'lockfileVersion': 3,
                'packages': {'': {}, 'node_modules/foo': {'version': '1.0.0'}},
            }), encoding='utf-8')
            graph = discover(root)
            cdx = cyclonedx_bom_with_providers(graph)
            spdx = spdx_document(graph, created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            comparison = compare_sboms(cdx, spdx)
            self.assertTrue(comparison.consistent)
            self.assertEqual(comparison.cyclonedx_purls, ('pkg:npm/foo@1.0.0',))

    def test_provider_relationships_are_consistent_between_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"name":"app","version":"1","packageManager":"npm@11"}', encoding='utf-8')
            (root / 'package-lock.json').write_text(json.dumps({
                'lockfileVersion': 3,
                'packages': {
                    '': {'name':'app','version':'1'},
                    'node_modules/a': {'version':'1.0.0'},
                    'node_modules/a/node_modules/b': {'version':'2.0.0'},
                },
            }), encoding='utf-8')
            tree = json.dumps({'name':'app','version':'1','dependencies':{'a':{'version':'1.0.0','dependencies':{'b':{'version':'2.0.0'}}}}})
            root_name, root_version, packages, edges, problems = parse_npm_ls(tree, '.:node')
            npm = NpmGraphResult(NpmGraphPlan('.:node', root), packages, edges, 0, root_name, root_version, problems)
            graph = discover(root)
            cdx = cyclonedx_bom_with_providers(graph, npm_results=[npm])
            spdx = spdx_document(graph, npm_results=[npm], created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            comparison = compare_sboms(cdx, spdx)
            self.assertTrue(comparison.consistent)
            self.assertEqual(comparison.cyclonedx_relationships, (('pkg:npm/a@1.0.0', 'pkg:npm/b@2.0.0'),))

    def test_format_drift_is_reported_explicitly(self) -> None:
        cdx = {'components': [{'bom-ref':'pkg:npm/a@1','purl':'pkg:npm/a@1'}]}
        spdx = {'packages': []}
        comparison = compare_sboms(cdx, spdx)
        self.assertFalse(comparison.consistent)
        self.assertEqual(comparison.only_cyclonedx, ('pkg:npm/a@1',))

    def test_local_format_specific_ids_are_not_forced_into_purl_equivalence(self) -> None:
        cdx = {'components': [{'bom-ref':'urn:upm:local:1','name':'local'}]}
        spdx = {'packages': [{'SPDXID':'SPDXRef-local','name':'local','externalRefs':[]}]}
        self.assertTrue(compare_sboms(cdx, spdx).consistent)


if __name__ == '__main__':
    unittest.main()
