from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.workspace_health import cargo_workspace_findings, node_workspace_findings, workspace_findings


class WorkspaceHealthTests(unittest.TestCase):
    def test_manager_mismatch_is_error_and_unlisted_package_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text(json.dumps({
                'packageManager': 'npm@11',
                'workspaces': ['packages/*'],
            }), encoding='utf-8')
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            member = root / 'packages' / 'app'
            stray = root / 'tools' / 'stray'
            member.mkdir(parents=True); stray.mkdir(parents=True)
            (member / 'package.json').write_text('{"name":"app","packageManager":"yarn@4"}', encoding='utf-8')
            (member / 'yarn.lock').write_text('', encoding='utf-8')
            (stray / 'package.json').write_text('{"name":"stray"}', encoding='utf-8')

            findings = node_workspace_findings(discover(root))
            by_code = {finding.code: finding for finding in findings}
            self.assertEqual(by_code['workspace.manager-mismatch'].severity, 'error')
            self.assertEqual(by_code['workspace.unlisted-package'].severity, 'warning')
            self.assertIn('packages/app', by_code['workspace.manager-mismatch'].component or '')

    def test_duplicate_names_are_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"workspaces":["packages/*"]}', encoding='utf-8')
            for name in ('a', 'b'):
                directory = root / 'packages' / name
                directory.mkdir(parents=True)
                (directory / 'package.json').write_text('{"name":"same"}', encoding='utf-8')
            findings = node_workspace_findings(discover(root))
            finding = next(item for item in findings if item.code == 'workspace.duplicate-package-name')
            self.assertEqual(finding.severity, 'error')

    def test_invalid_workspace_shape_is_error_finding_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"workspaces":"packages/*"}', encoding='utf-8')
            findings = node_workspace_findings(discover(root))
            self.assertEqual(findings[0].code, 'workspace.invalid')
            self.assertEqual(findings[0].severity, 'error')

    def test_stale_cargo_member_pattern_is_local_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Cargo.toml').write_text('[workspace]\nmembers=["missing/*"]\n', encoding='utf-8')
            (root / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')

            findings = cargo_workspace_findings(discover(root))

            finding = next(item for item in findings if item.code == 'cargo.workspace.pattern-unmatched')
            self.assertEqual(finding.severity, 'warning')
            self.assertIn('missing/*', finding.message)

    def test_aggregate_workspace_health_contains_node_and_cargo_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / 'node'; rust = root / 'rust'
            node.mkdir(); rust.mkdir()
            (node / 'package.json').write_text('{"workspaces":["missing/*"]}', encoding='utf-8')
            (rust / 'Cargo.toml').write_text('[workspace]\nmembers=["missing/*"]\n', encoding='utf-8')
            (rust / 'Cargo.lock').write_text('version=4\n', encoding='utf-8')

            codes = {finding.code for finding in workspace_findings(discover(root))}

            self.assertIn('workspace.pattern-unmatched', codes)
            self.assertIn('cargo.workspace.pattern-unmatched', codes)


if __name__ == '__main__':
    unittest.main()
