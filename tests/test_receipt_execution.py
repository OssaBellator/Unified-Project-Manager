from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.receipt_execution import execute_plans_with_receipt


@dataclass(frozen=True)
class FakePlan:
    component: str
    manager: str
    cwd: Path
    argv: tuple[str, ...]


@dataclass
class FakeResult:
    returncode: int


class ReceiptExecutionTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
        (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')

    def test_successful_execution_records_actual_post_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            plan = FakePlan('.:node', 'npm', root, ('npm', 'install', 'x'))

            def execute(_plan):
                (root / 'package.json').write_text('{"packageManager":"npm@11","dependencies":{"x":"1"}}', encoding='utf-8')
                return FakeResult(0)

            execution = execute_plans_with_receipt(graph, 'add', [plan], execute)
            self.assertTrue(execution.succeeded)
            changes = {item.path: item.status for item in execution.receipt.changes}
            self.assertEqual(changes['package.json'], 'changed')
            self.assertTrue(execution.receipt_path.is_file())

    def test_failure_stops_batch_but_records_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            plans = [
                FakePlan('.:node', 'npm', root, ('npm', 'install', 'first')),
                FakePlan('.:node', 'npm', root, ('npm', 'install', 'second')),
            ]
            calls = []

            def execute(plan):
                calls.append(plan.argv[-1])
                (root / 'package.json').write_text('{"packageManager":"npm@11","dependencies":{"partial":"1"}}', encoding='utf-8')
                return FakeResult(2)

            execution = execute_plans_with_receipt(graph, 'batch-add', plans, execute)
            self.assertFalse(execution.succeeded)
            self.assertEqual(calls, ['first'])
            self.assertEqual(len(execution.receipt.commands), 1)
            changed = next(item for item in execution.receipt.changes if item.path == 'package.json')
            self.assertEqual(changed.status, 'changed')

    def test_secrets_are_redacted_when_execution_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            plan = FakePlan('.:node', 'npm', root, ('npm', 'config', 'set', '--token', 'secret'))
            execution = execute_plans_with_receipt(graph, 'exec', [plan], lambda _plan: FakeResult(0))
            rendered = ' '.join(execution.receipt.commands[0].argv)
            self.assertNotIn('secret', rendered)
            self.assertIn('<redacted>', rendered)


if __name__ == '__main__':
    unittest.main()
