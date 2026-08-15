from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evidence_semantics import validate_project_evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm evidence verify",
        description="Validate the anchored evidence byte set and strong-format evidence semantics locally",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def verify_evidence_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        message = f"project path is not a directory: {root}"
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2

    try:
        validation = validate_project_evidence(root)
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    payload = {
        **validation.to_dict(),
        "network_executed": False,
        "scanner_execution": False,
        "native_provider_execution": False,
        "mutation_executed": False,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif validation.valid:
        print(f"Project evidence: valid ({validation.manifest.evidence_set_id})")
        for item in validation.semantic_checks:
            state = "valid" if item.valid is True else "compatibility/hash-only" if item.valid is None else "invalid"
            print(f"  {item.path}: {state} [{item.assurance}]")
    else:
        print(f"Project evidence: invalid ({validation.reason})")
        manifest = validation.manifest
        for path in manifest.missing:
            print(f"  missing     {path}")
        for path in manifest.changed:
            print(f"  changed     {path}")
        for path in manifest.unexpected:
            print(f"  unexpected  {path}")
        for item in validation.semantic_checks:
            if item.valid is False:
                print(f"  invalid     {item.path}: {item.reason}")
    return 0 if validation.valid else 1


def main(argv: list[str] | None = None) -> int:
    return verify_evidence_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
