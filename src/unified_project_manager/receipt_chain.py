from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .receipt_history import list_receipt_history

CHAIN_VERSION = 1
CHAIN_PATH = Path('.upm/receipt-chain.json')
GENESIS = '0' * 64


class ReceiptChainError(ValueError):
    """Raised when a receipt-chain manifest is invalid or inconsistent."""


@dataclass(frozen=True)
class ReceiptChainEntry:
    sequence: int
    receipt_id: str
    receipt_path: str
    previous_hash: str
    chain_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiptChain:
    version: int
    generated_at: str
    head_hash: str
    entries: tuple[ReceiptChainEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'generated_at': self.generated_at,
            'head_hash': self.head_hash,
            'entries': [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class ReceiptChainValidation:
    valid: bool
    head_hash: str | None
    anchor_digest: str | None
    missing_receipts: tuple[str, ...]
    unexpected_receipts: tuple[str, ...]
    invalid_receipts: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'valid': self.valid,
            'head_hash': self.head_hash,
            'anchor_digest': self.anchor_digest,
            'missing_receipts': list(self.missing_receipts),
            'unexpected_receipts': list(self.unexpected_receipts),
            'invalid_receipts': list(self.invalid_receipts),
            'reason': self.reason,
            'authenticated': False,
        }


def _entry_hash(previous: str, receipt_id: str, receipt_path: str, sequence: int) -> str:
    payload = '\0'.join((previous, str(sequence), receipt_id, receipt_path))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def build_receipt_chain(root: str | Path, *, created: datetime | None = None) -> ReceiptChain:
    root_path = Path(root).expanduser().resolve()
    history = list_receipt_history(root_path)
    invalid = [item.path for item in history if not item.valid]
    if invalid:
        raise ReceiptChainError('Cannot build a receipt chain while invalid receipt files exist: ' + ', '.join(invalid))
    valid = [item for item in history if item.valid and item.receipt_id]
    previous = GENESIS
    entries: list[ReceiptChainEntry] = []
    for sequence, item in enumerate(valid, start=1):
        path = Path(item.path).resolve()
        try:
            relative = path.relative_to(root_path).as_posix()
        except ValueError as exc:
            raise ReceiptChainError(f'Receipt path escapes project root: {path}') from exc
        chain_hash = _entry_hash(previous, item.receipt_id or '', relative, sequence)
        entries.append(ReceiptChainEntry(sequence, item.receipt_id or '', relative, previous, chain_hash))
        previous = chain_hash
    timestamp = created or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generated_at = timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return ReceiptChain(CHAIN_VERSION, generated_at, previous, tuple(entries))


def canonical_chain_bytes(chain: ReceiptChain | dict[str, Any]) -> bytes:
    data = chain.to_dict() if isinstance(chain, ReceiptChain) else chain
    stable = {
        'version': data.get('version'),
        'head_hash': data.get('head_hash'),
        'entries': data.get('entries'),
    }
    return (json.dumps(stable, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def receipt_chain_anchor_digest(chain: ReceiptChain | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_chain_bytes(chain)).hexdigest()


def write_receipt_chain(root: str | Path, chain: ReceiptChain, path: str | Path | None = None) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = root_path / CHAIN_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(chain.to_dict(), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target


def _read_chain(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptChainError(f'Could not read receipt chain {path}: {exc}') from exc
    if not isinstance(data, dict) or data.get('version') != CHAIN_VERSION:
        raise ReceiptChainError(f'Unsupported or invalid receipt chain: {path}')
    if not isinstance(data.get('head_hash'), str) or not isinstance(data.get('entries'), list):
        raise ReceiptChainError(f'Receipt chain structure is invalid: {path}')
    return data


def validate_receipt_chain(root: str | Path, path: str | Path | None = None) -> ReceiptChainValidation:
    root_path = Path(root).expanduser().resolve()
    target = root_path / CHAIN_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    if not target.is_file():
        return ReceiptChainValidation(False, None, None, (), (), (), 'No receipt-chain manifest exists.')
    try:
        data = _read_chain(target)
    except ReceiptChainError as exc:
        return ReceiptChainValidation(False, None, None, (), (), (), str(exc))

    entries = data['entries']
    previous = GENESIS
    expected_receipts: dict[str, str] = {}
    for expected_sequence, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            return ReceiptChainValidation(False, data['head_hash'], receipt_chain_anchor_digest(data), (), (), (), 'Receipt-chain entry is not an object.')
        sequence = raw.get('sequence')
        receipt_id = raw.get('receipt_id')
        receipt_path = raw.get('receipt_path')
        previous_hash = raw.get('previous_hash')
        chain_hash = raw.get('chain_hash')
        if sequence != expected_sequence or not all(isinstance(value, str) for value in (receipt_id, receipt_path, previous_hash, chain_hash)):
            return ReceiptChainValidation(False, data['head_hash'], receipt_chain_anchor_digest(data), (), (), (), 'Receipt-chain entry identity/order is invalid.')
        if receipt_path in expected_receipts:
            return ReceiptChainValidation(False, data['head_hash'], receipt_chain_anchor_digest(data), (), (), (), f'Receipt-chain path appears more than once: {receipt_path}')
        if previous_hash != previous or chain_hash != _entry_hash(previous, receipt_id, receipt_path, sequence):
            return ReceiptChainValidation(False, data['head_hash'], receipt_chain_anchor_digest(data), (), (), (), 'Receipt-chain hash linkage is invalid.')
        expected_receipts[receipt_path] = receipt_id
        previous = chain_hash
    if previous != data['head_hash']:
        return ReceiptChainValidation(False, data['head_hash'], receipt_chain_anchor_digest(data), (), (), (), 'Receipt-chain head does not match the final entry.')

    history = list_receipt_history(root_path)
    current_receipts: dict[str, str | None] = {}
    invalid_receipts: list[str] = []
    for item in history:
        receipt = Path(item.path).resolve()
        try:
            relative = receipt.relative_to(root_path).as_posix()
        except ValueError:
            relative = str(receipt)
        current_receipts[relative] = item.receipt_id
        if not item.valid:
            invalid_receipts.append(relative)
            continue
        anchored_id = expected_receipts.get(relative)
        if anchored_id is not None and item.receipt_id != anchored_id:
            invalid_receipts.append(relative)

    expected_paths = set(expected_receipts)
    current_paths = set(current_receipts)
    missing = tuple(sorted(expected_paths - current_paths))
    unexpected = tuple(sorted(current_paths - expected_paths))
    invalid_tuple = tuple(sorted(set(invalid_receipts)))
    valid = not missing and not unexpected and not invalid_tuple
    reason = None if valid else 'Current receipt files do not exactly match the anchored receipt identities and chain manifest.'
    return ReceiptChainValidation(
        valid,
        data['head_hash'],
        receipt_chain_anchor_digest(data),
        missing,
        unexpected,
        invalid_tuple,
        reason,
    )
