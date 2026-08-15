from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .receipt_chain import (
    CHAIN_PATH,
    ReceiptChainError,
    build_receipt_chain,
    receipt_chain_anchor_digest,
    validate_receipt_chain,
    write_receipt_chain,
)
from .receipt_history import receipt_history_status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm receipts",
        description="Inspect persisted local mutation-receipt history and current-state drift",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _chain_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm receipts chain",
        description="Preview, write, or validate a deterministic receipt-chain manifest",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--apply", action="store_true", help="Write the proposed receipt-chain manifest; otherwise preview only")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    return root


def receipts_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _root(args.path)
        status = receipt_history_status(discover(root))
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    validations = status.get("validations", [])
    invalid = [item for item in validations if not item.get("valid")]
    drifted = status.get("state") == "drifted"
    chain_path = root / CHAIN_PATH
    chain_validation = validate_receipt_chain(root) if chain_path.is_file() else None
    chain_invalid = chain_validation is not None and not chain_validation.valid

    payload = {
        **status,
        "invalid_receipts": len(invalid),
        "current_state_drift": drifted,
        "receipt_chain": chain_validation.to_dict() if chain_validation else {
            "present": False,
            "valid": None,
            "path": CHAIN_PATH.as_posix(),
        },
        "network_executed": False,
        "mutation_executed": False,
    }

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not validations:
        print("No mutation receipts recorded for this project.")
    else:
        print(f"Receipt history: {len(validations)} receipt(s); state={status.get('state')}")
        for item in validations:
            marker = "✓" if item.get("valid") else "x"
            operation = item.get("operation") or "unknown"
            returncode = item.get("returncode")
            result = "success" if item.get("succeeded") else f"failed/{returncode}"
            print(f"{marker} {item.get('receipt_id')}  {operation}  {result}")
            for issue in item.get("issues", []):
                print(f"    {issue}")
        if drifted:
            print("Current native project state differs from the latest recorded post-mutation state:")
            for change in status.get("changes", []):
                print(f"  {change['status']:<9} {change['path']}")
        elif status.get("state") == "current":
            print("Current native project state matches the latest receipt baseline.")
        if chain_validation is None:
            print("Receipt chain: absent (optional; preview with 'upm receipts chain').")
        elif chain_validation.valid:
            print(f"Receipt chain: valid; anchor digest={chain_validation.anchor_digest}")
        else:
            print(f"Receipt chain: invalid ({chain_validation.reason})")

    return 1 if invalid or drifted or chain_invalid else 0


def receipt_chain_command(argv: list[str]) -> int:
    args = _chain_parser().parse_args(argv)
    try:
        root = _root(args.path)
        chain = build_receipt_chain(root)
    except (OSError, ValueError, ReceiptChainError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    anchor_digest = receipt_chain_anchor_digest(chain)
    existing_path = root / CHAIN_PATH
    existing = validate_receipt_chain(root) if existing_path.is_file() else None

    if not args.apply:
        payload = {
            "executed": False,
            "proposed": chain.to_dict(),
            "anchor_digest": anchor_digest,
            "path": CHAIN_PATH.as_posix(),
            "existing": existing.to_dict() if existing else None,
            "authenticated": False,
            "network_executed": False,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Receipt chain entries: {len(chain.entries)}")
            print(f"Proposed head: {chain.head_hash}")
            print(f"Anchor digest: {anchor_digest}")
            if existing:
                print(f"Existing chain: {'valid' if existing.valid else 'invalid'}")
            print("Preview only. Re-run with --apply to write the local chain manifest.")
        return 0

    try:
        target = write_receipt_chain(root, chain)
    except OSError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    validation = validate_receipt_chain(root)
    if args.as_json:
        print(json.dumps({
            "executed": True,
            "path": str(target),
            "chain": chain.to_dict(),
            "anchor_digest": anchor_digest,
            "validation": validation.to_dict(),
            "authenticated": False,
        }, indent=2, sort_keys=True))
    else:
        print(str(target))
        print(f"Head: {chain.head_hash}")
        print(f"Anchor digest: {anchor_digest}")
        print("This local hash chain is tamper-evident but not externally authenticated.")
    return 0 if validation.valid else 1


def dispatch_receipt_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "receipts":
        return None
    if len(arguments) >= 2 and arguments[1] == "chain":
        return receipt_chain_command(arguments[2:])
    return receipts_command(arguments[1:])
