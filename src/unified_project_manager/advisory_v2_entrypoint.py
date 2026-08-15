from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .advisory_evidence_v2 import (
    AdvisoryEvidenceError,
    build_advisory_evidence_v2,
    load_advisory_evidence_v2,
    write_advisory_evidence_v2,
)
from .discovery import discover
from .security import SecurityScanError, execute_security_scan, plan_security_scan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm audit-v2",
        description="Preview or execute an OSV scan and persist self-validating advisory evidence v2",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--native-go", action="store_true", help="Use authoritative offline selected Go modules before scanning")
    parser.add_argument("--apply", action="store_true", help="Run OSV-Scanner and write v2 evidence; preview is the default")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def audit_v2_command(argv: list[str]) -> int:
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
        graph = discover(root)
        plan = plan_security_scan(graph, native_go=args.native_go)
    except (OSError, ValueError, SecurityScanError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        payload = {
            "executed": False,
            "plan": plan.to_dict(),
            "evidence_version": 2,
            "evidence_path": ".upm/audits/osv-v2.json",
            "network_may_be_used_on_apply": True,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Command: {shlex.join(plan.argv_template)}")
            print("Evidence target: .upm/audits/osv-v2.json")
            print("Preview only. Re-run with --apply to execute OSV-Scanner and persist v2 evidence.")
        return 0

    try:
        result = execute_security_scan(graph, plan)
    except SecurityScanError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc), "plan": plan.to_dict()}, indent=2, sort_keys=True))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not result.scanner_succeeded:
        payload = result.to_dict()
        payload["evidence"] = None
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"OSV-Scanner failed with exit code {result.returncode}.", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        return 2
    if result.bom is None or result.report is None:
        message = "A valid v2 advisory evidence record requires the exact scanned BOM and structured OSV report."
        if args.as_json:
            print(json.dumps({"error": message, "result": result.to_dict()}, indent=2, sort_keys=True))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2

    try:
        evidence = build_advisory_evidence_v2(
            result.bom,
            result.report,
            scanner_returncode=result.returncode,
            inventory_mode="native-go" if plan.native_go else "static-resolved",
        )
        target = write_advisory_evidence_v2(root, evidence)
        validation = load_advisory_evidence_v2(root, bom=result.bom)
    except (AdvisoryEvidenceError, OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc), "result": result.to_dict()}, indent=2, sort_keys=True))
        else:
            print(f"upm: could not persist advisory evidence v2: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps({
            "executed": True,
            "scanner": result.to_dict(),
            "evidence": evidence.to_dict(),
            "evidence_path": str(target),
            "validation": validation.to_dict(),
        }, indent=2, sort_keys=True))
    else:
        summary = evidence.summary
        if evidence.vulnerable:
            print(
                f"Vulnerabilities found: {summary.vulnerabilities} unique advisory ID(s) "
                f"across {summary.affected_packages} affected package occurrence(s)."
            )
        else:
            print("No known vulnerabilities were reported for the scanned inventory.")
        print(f"Advisory evidence v2: {target}")
        print(f"Evidence ID: {evidence.evidence_id}")
    if not validation.valid:
        return 2
    return 1 if evidence.vulnerable else 0


def main(argv: list[str] | None = None) -> int:
    return audit_v2_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
