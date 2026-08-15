from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.evidence_status import local_evidence_status


class EvidenceStatusTests(unittest.TestCase):
    def test_status_is_local_and_reports_provider_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            data = local_evidence_status(discover(root))
            self.assertFalse(data['network_executed'])
            self.assertFalse(data['native_provider_execution'])
            self.assertFalse(data['scanner_execution'])
            coverage = data['summary']['relationship_provider_coverage']
            self.assertEqual(coverage, {'supported': 1, 'total': 1})
            self.assertEqual(data['advisory_evidence']['state'], 'absent')
            self.assertEqual(data['mutation_receipts']['state'], 'absent')

    def test_workspace_errors_become_blockers_without_running_workspace_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11","workspaces":["packages/*"]}', encoding='utf-8')
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            first = root / 'packages' / 'a'; second = root / 'packages' / 'b'
            first.mkdir(parents=True); second.mkdir(parents=True)
            (first / 'package.json').write_text('{"name":"same"}', encoding='utf-8')
            (second / 'package.json').write_text('{"name":"same"}', encoding='utf-8')
            data = local_evidence_status(discover(root))
            self.assertGreaterEqual(data['summary']['workspace_errors'], 1)
            self.assertIn('workspace-errors', data['summary']['blockers'])

    def test_policy_violation_is_a_blocker_but_does_not_execute_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            (root / 'upm.toml').write_text('[policy]\nrequire_advisory_evidence=true\n', encoding='utf-8')
            data = local_evidence_status(discover(root))
            self.assertFalse(data['policy']['passed'])
            self.assertIn('policy-violations', data['summary']['blockers'])
            self.assertFalse(data['scanner_execution'])


if __name__ == '__main__':
    unittest.main()
