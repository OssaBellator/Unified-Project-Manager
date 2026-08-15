from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.fleet_provenance import (
    aggregate_package_provenance,
    fleet_package_uses,
    project_package_uses,
    version_divergence,
)


class FleetProvenanceTests(unittest.TestCase):
    def _npm(self, root: Path, package_version: str) -> None:
        root.mkdir()
        (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
        (root / 'package-lock.json').write_text(json.dumps({
            'lockfileVersion': 3,
            'packages': {'': {}, 'node_modules/foo': {'version': package_version}},
        }), encoding='utf-8')

    def test_same_registry_identity_groups_across_projects_without_physical_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / 'one'; two = root / 'two'
            self._npm(one, '1.0.0'); self._npm(two, '1.0.0')
            uses, skipped = fleet_package_uses(roots=[one, two])
            self.assertEqual(skipped, [])
            groups = aggregate_package_provenance(uses)
            self.assertEqual(len(groups), 1)
            group = groups[0]
            self.assertEqual(group.purl, 'pkg:npm/foo@1.0.0')
            self.assertEqual(group.projects, 2)
            data = group.to_dict()
            self.assertTrue(data['shared_across_projects'])
            self.assertFalse(data['physical_duplication_known'])
            self.assertFalse(data['reclaimable'])

    def test_version_divergence_is_logical_not_reclaimability_advice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / 'one'; two = root / 'two'
            self._npm(one, '1.0.0'); self._npm(two, '2.0.0')
            groups = aggregate_package_provenance(fleet_package_uses(roots=[one, two])[0])
            divergence = version_divergence(groups)
            self.assertEqual(divergence[0]['versions'], ['1.0.0', '2.0.0'])
            self.assertFalse(divergence[0]['physical_duplication_known'])
            self.assertFalse(divergence[0]['reclaimable'])

    def test_non_registry_identity_does_not_receive_registry_purl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Cargo.toml').write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding='utf-8')
            (root / 'Cargo.lock').write_text('version=4\n[[package]]\nname="local"\nversion="0.1.0"\n', encoding='utf-8')
            use = project_package_uses(root)[0]
            self.assertIsNone(use.purl)
            self.assertTrue(use.identity.startswith('urn:upm:resolved:sha256:'))

    def test_missing_projects_are_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'; missing = root / 'missing'
            self._npm(project, '1.0.0')
            uses, skipped = fleet_package_uses(roots=[project, missing])
            self.assertGreater(len(uses), 0)
            self.assertEqual(skipped, [str(missing)])


if __name__ == '__main__':
    unittest.main()
