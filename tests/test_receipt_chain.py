from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.receipt_chain import (
    build_receipt_chain,
    receipt_chain_anchor_digest,
    validate_receipt_chain,
    write_receipt_chain,
)
from unified_project_manager.receipts import build_mutation_receipt, capture_project_state, write_mutation_receipt


class ReceiptChainTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
        (root / 'package-lock.json').write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding='utf-8')

    def _add_receipt(self, root: Path, operation: str, hour: int) -> Path:
        state = capture_project_state(discover(root))
        receipt = build_mutation_receipt(
            root,
            operation,
            [{'component': '.:node', 'manager': 'npm', 'cwd': '.', 'argv': ['npm', 'ci'], 'returncode': 0}],
            state,
            state,
            created=datetime(2026, 8, 15, hour, 0, tzinfo=timezone.utc),
        )
        return write_mutation_receipt(root, receipt)

    def test_chain_validates_exact_receipt_set_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._add_receipt(root, 'sync', 1)
            self._add_receipt(root, 'install', 2)
            chain = build_receipt_chain(root, created=datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc))
            write_receipt_chain(root, chain)
            validation = validate_receipt_chain(root)
            self.assertTrue(validation.valid)
            self.assertEqual(validation.head_hash, chain.head_hash)
            self.assertEqual(validation.anchor_digest, receipt_chain_anchor_digest(chain))
            self.assertFalse(validation.to_dict()['authenticated'])

    def test_deleted_receipt_is_detected_against_existing_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            first = self._add_receipt(root, 'sync', 1)
            self._add_receipt(root, 'install', 2)
            write_receipt_chain(root, build_receipt_chain(root))
            first.unlink()
            validation = validate_receipt_chain(root)
            self.assertFalse(validation.valid)
            self.assertIn(first.relative_to(root).as_posix(), validation.missing_receipts)

    def test_new_unanchored_receipt_is_reported_as_unexpected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._add_receipt(root, 'sync', 1)
            write_receipt_chain(root, build_receipt_chain(root))
            second = self._add_receipt(root, 'install', 2)
            validation = validate_receipt_chain(root)
            self.assertFalse(validation.valid)
            self.assertIn(second.relative_to(root).as_posix(), validation.unexpected_receipts)

    def test_manifest_link_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._add_receipt(root, 'sync', 1)
            path = write_receipt_chain(root, build_receipt_chain(root))
            data = json.loads(path.read_text(encoding='utf-8'))
            data['entries'][0]['previous_hash'] = 'f' * 64
            path.write_text(json.dumps(data), encoding='utf-8')
            validation = validate_receipt_chain(root)
            self.assertFalse(validation.valid)
            self.assertIn('hash linkage', validation.reason or '')

    def test_anchor_digest_changes_with_chain_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._add_receipt(root, 'sync', 1)
            first = build_receipt_chain(root)
            first_digest = receipt_chain_anchor_digest(first)
            self._add_receipt(root, 'install', 2)
            second = build_receipt_chain(root)
            self.assertNotEqual(first_digest, receipt_chain_anchor_digest(second))


if __name__ == '__main__':
    unittest.main()
