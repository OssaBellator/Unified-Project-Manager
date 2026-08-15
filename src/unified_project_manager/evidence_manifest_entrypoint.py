from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evidence_manifest import (
    DEFAULT_EVIDENCE_MANIFEST_PATH,
    EvidenceManifestError,
    build_evidence_manifest,
    evidence_manifest_anchor_digest,
    load_evidence_manifest,
    write_evidence_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm evidence",
        description="Preview/write or validate a deterministic project evidence manifest",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("manifest", help="Preview or write the current evidence manifest")
    build.add_argument("path", nargs="?", default=".")
    build.add_argument("--apply", action="store_true", help="Write .upm/evidence-manifest.json; otherwise preview only")
    build.add_argument("--json", action="store_true", dest="as_json")

    validate = subparsers.add_parser("validate", help="Validate the persisted evidence manifest against current local evidence")
    validate.add_argument("path", nargs="?", default=".")
    validate.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise EvidenceManifestError(f"Project root is not a directory: {root}")
    return root


def evidence_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _root(args.path)
    except EvidenceManifestError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        validation = load_evidence_manifest(root)
        if args.as_json:
            print(json.dumps({
                **validation.to_dict(),
                "path": DEFAULT_EVIDENCE_MANIFEST_PATH.as_posix(),
                "network_executed": False,
                "mutation_executed": False,
            }, indent=2, sort_keys=True))
        elif validation.valid:
            print(f"Evidence manifest: valid ({validation.evidence_set_id})")
        else:
            print(f"Evidence manifest: invalid ({validation.reason})")
            for path in validation.missing:
                print(f"  missing     {path}")
            for path in validation.changed:
                print(f"  changed     {path}")
            for path in validation.unexpected:
                print(f"  unexpected  {path}")
        return 0 if validation.valid else 1

    try:
        manifest = build_evidence_manifest(root)
    except EvidenceManifestError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    anchor = evidence_manifest_anchor_digest(manifest)

    if not args.apply:
        payload = {
            "executed": False,
            "manifest": manifest.to_dict(),
            "anchor_digest": anchor,
            "path": DEFAULT_EVIDENCE_MANIFEST_PATH.as_posix(),
            "authenticated": False,
            "network_executed": False,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Evidence artifacts: {len(manifest.artifacts)}")
            print(f"Evidence-set ID: {manifest.evidence_set_id}")
            print(f"Anchor digest: {anchor}")
            print("Preview only. Re-run with --apply to write the local evidence manifest.")
        return 0

    try:
        target = write_evidence_manifest(root, manifest)
    except (OSError, EvidenceManifestError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    validation = load_evidence_manifest(root)
    if args.as_json:
        print(json.dumps({
            "executed": True,
            "path": str(target),
            "manifest": manifest.to_dict(),
            "anchor_digest": anchor,
            "validation": validation.to_dict(),
            "authenticated": False,
        }, indent=2, sort_keys=True))
    else:
        print(str(target))
        print(f"Evidence-set ID: {manifest.evidence_set_id}")
        print(f"Anchor digest: {anchor}")
        print("This local evidence manifest is tamper-evident but not externally authenticated.")
    return 0 if validation.valid else 1


def main(argv: list[str] | None = None) -> int:
    return evidence_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
