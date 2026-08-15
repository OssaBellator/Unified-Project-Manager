from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.receipts import (
    build_mutation_receipt,
    capture_project_state,
    redact_argv,
    write_mutation_receipt,
)


class ReceiptTests(unittest.TestCase):
    def test_redacts_common_secret_argument_forms(self) -> None:
        argv = redact_argv([
            'npm', 'config', 'set', '//registry.example/:_authToken=secret',
            '--password', 'hunter2', '--token=abc', 'react',
        ])
        self.assertNotIn('secret', ' '.join(argv))
        self.assertNotIn('hunter2', ' '.join(argv))
        self.assertNotIn('abc', ' '.join(argv))
        self.assertIn('react', argv)

    def test_receipt_captures_changed_and_added_native_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            graph_before = discover(root)
            before = capture_project_state(graph_before)
            (root / 'package.json').write_text('{"packageManager":"npm@11","dependencies":{"x":"1"}}', encoding='utf-8')
            (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')
            after = capture_project_state(discover(root))
            receipt = build_mutation_receipt(
                root,
                'add',
                [{
                    'component': '.:node', 'manager': 'npm', 'cwd': root,
                    'argv': ['npm', 'install', 'x'], 'returncode': 0,
                }],
                before,
                after,
                created=datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc),
            )
            changes = {item.path: item.status for item in receipt.changes}
            self.assertEqual(changes['package.json'], 'changed')
            self.assertEqual(changes['package-lock.json'], 'added')
            self.assertTrue(receipt.succeeded)

    def test_failed_command_is_recorded_without_stdout_or_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = build_mutation_receipt(
                root,
                'sync',
                [{'component': '.:node', 'manager': 'npm', 'cwd': '.', 'argv': ['npm', 'ci'], 'returncode': 2}],
                (),
                (),
            )
            data = receipt.to_dict()
            self.assertFalse(data['succeeded'])
            self.assertNotIn('stdout', data['commands'][0])
            self.assertNotIn('stderr', data['commands'][0])
            self.assertNotIn('environment', data['commands'][0])

    def test_receipt_write_is_atomic_json_under_upm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = build_mutation_receipt(root, 'install', [], (), ())
            path = write_mutation_receipt(root, receipt)
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent, root / '.upm' / 'receipts')
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['receipt_id'], receipt.receipt_id)
            self.assertFalse(path.with_suffix(path.suffix + '.tmp').exists())

    def test_extra_state_path_must_remain_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'project'
            outside = Path(temporary) / 'outside.txt'
            root.mkdir(); outside.write_text('x', encoding='utf-8')
            (root / 'package.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                capture_project_state(discover(root), extra_paths=[outside])


if __name__ == '__main__':
    unittest.main()
