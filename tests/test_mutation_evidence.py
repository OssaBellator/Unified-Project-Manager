from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.mutation_evidence import execute_plans_with_evidence


@dataclass(frozen=True)
class Plan:
    component: str
    manager: str
    cwd: Path
    argv: tuple[str, ...]


@dataclass
class Result:
    returncode: int


class MutationEvidenceTests(unittest.TestCase):
    def test_successful_add_records_file_and_dependency_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            graph = discover(root)
            plan = Plan('.:node', 'npm', root, ('npm', 'install', 'react'))

            def execute(_plan):
                (root / 'package.json').write_text('{"packageManager":"npm@11","dependencies":{"react":"^19"}}', encoding='utf-8')
                (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{},"node_modules/react":{"version":"19.0.0"}}}', encoding='utf-8')
                return Result(0)

            evidence = execute_plans_with_evidence(graph, 'add', [plan], execute)
            self.assertTrue(evidence.succeeded)
            self.assertTrue(evidence.dependency_delta.changed)
            self.assertEqual(evidence.dependency_delta.direct[0].status, 'added')
            self.assertEqual(evidence.dependency_delta.resolved[0].status, 'added')
            data = evidence.to_dict()
            self.assertFalse(data['resolver_interpretation'])
            self.assertTrue(data['execution']['receipt_path'])

    def test_failed_partial_mutation_still_reports_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            graph = discover(root)
            plan = Plan('.:node', 'npm', root, ('npm', 'install', 'broken'))

            def execute(_plan):
                (root / 'package.json').write_text('{"packageManager":"npm@11","dependencies":{"partial":"1"}}', encoding='utf-8')
                return Result(2)

            evidence = execute_plans_with_evidence(graph, 'add', [plan], execute)
            self.assertFalse(evidence.succeeded)
            self.assertTrue(evidence.dependency_delta.changed)
            self.assertEqual(evidence.dependency_delta.direct[0].name, 'partial')


if __name__ == '__main__':
    unittest.main()
