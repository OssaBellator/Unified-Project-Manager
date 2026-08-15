from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.receipt_history import latest_receipt_drift, validate_receipt_file
from unified_project_manager.receipts import build_mutation_receipt, capture_project_state, write_mutation_receipt


class ReceiptHistoryTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
        (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')

    def _receipt(self, root: Path) -> Path:
        graph = discover(root)
        state = capture_project_state(graph)
        receipt = build_mutation_receipt(
            root,
            'sync',
            [{'component': '.:node', 'manager': 'npm', 'cwd': '.', 'argv': ['npm', 'ci'], 'returncode': 0}],
            state,
            state,
        )
        return write_mutation_receipt(root, receipt)

    def test_valid_receipt_and_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            path = self._receipt(root)
            self.assertTrue(validate_receipt_file(path).valid)
            status = latest_receipt_drift(discover(root))
            self.assertEqual(status.state, 'current')
            self.assertTrue(status.current)

    def test_manifest_change_after_receipt_is_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._receipt(root)
            (root / 'package.json').write_text('{"packageManager":"npm@11","dependencies":{"x":"1"}}', encoding='utf-8')
            status = latest_receipt_drift(discover(root))
            self.assertEqual(status.state, 'drifted')
            self.assertEqual(status.changes[0]['path'], 'package.json')

    def test_tampered_core_receipt_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            path = self._receipt(root)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['operation'] = 'remove'
            path.write_text(json.dumps(data), encoding='utf-8')
            validation = validate_receipt_file(path)
            self.assertFalse(validation.valid)
            self.assertIn('Receipt ID', validation.reason or '')

    def test_tampered_change_list_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            path = self._receipt(root)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['changes'][0]['status'] = 'changed'
            path.write_text(json.dumps(data), encoding='utf-8')
            validation = validate_receipt_file(path)
            self.assertFalse(validation.valid)
            self.assertIn('change list', validation.reason or '')

    def test_newer_invalid_receipt_is_reported_without_authenticity_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._receipt(root)
            bad = root / '.upm' / 'receipts' / 'zzzz-invalid.json'
            bad.write_text('{"version":1,"receipt_id":"bad"}', encoding='utf-8')
            status = latest_receipt_drift(discover(root))
            self.assertGreaterEqual(len(status.invalid_receipts), 1)


if __name__ == '__main__':
    unittest.main()
