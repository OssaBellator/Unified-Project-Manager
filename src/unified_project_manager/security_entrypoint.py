from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .audit_evidence import AuditEvidenceError, build_audit_evidence, write_audit_evidence
from .discovery import discover
from .security import SecurityScanError, execute_security_scan, plan_security_scan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm audit",
        description="Preview or execute vulnerability scanning over a temporary UPM CycloneDX SBOM",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--native-go", action="store_true", help="Enrich the temporary SBOM with authoritative offline selected Go modules during execution")
    parser.add_argument("--apply", action="store_true", help="Run OSV-Scanner and persist evidence; preview is the default because scanning may use the network")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def audit_command(argv: list[str]) -> int:
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
    except (OSError, SecurityScanError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        payload = {"executed": False, "plan": plan.to_dict(), "evidence_will_be_persisted": True}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            count = str(plan.package_count)
            if not plan.package_count_exact:
                count += "+ (Go inventory resolved on apply, offline)"
            print(f"Packages represented before native enrichment: {count}")
            print(f"Command: {shlex.join(plan.argv_template)}")
            print("Preview only. OSV-Scanner may use network access; re-run with --apply to execute and persist advisory evidence.")
        return 0

    try:
        result = execute_security_scan(graph, plan)
    except SecurityScanError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc), "plan": plan.to_dict()}, indent=2, sort_keys=True))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    evidence = None
    evidence_path = None
    if result.scanner_succeeded:
        if result.bom is None:
            message = "OSV-Scanner completed but UPM did not retain the exact scanned SBOM; refusing to persist unverifiable evidence."
            if args.as_json:
                print(json.dumps({"error": message, "result": result.to_dict()}, indent=2, sort_keys=True))
            else:
                print(f"upm: {message}", file=sys.stderr)
            return 2
        try:
            evidence = build_audit_evidence(
                result.bom,
                result,
                inventory_mode="native-go" if plan.native_go else "static-resolved",
            )
            evidence_path = write_audit_evidence(root, evidence)
        except (AuditEvidenceError, OSError, ValueError) as exc:
            if args.as_json:
                print(json.dumps({"error": f"Could not persist advisory evidence: {exc}", "result": result.to_dict()}, indent=2, sort_keys=True))
            else:
                print(f"upm: could not persist advisory evidence: {exc}", file=sys.stderr)
            return 2

    if args.as_json:
        payload = result.to_dict()
        payload["evidence"] = evidence.to_dict() if evidence else None
        payload["evidence_path"] = str(evidence_path) if evidence_path else None
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not result.scanner_succeeded:
        print(f"OSV-Scanner failed with exit code {result.returncode}.")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    else:
        summary = result.summary
        if result.vulnerable:
            print(
                f"Vulnerabilities found: {summary['vulnerabilities']} unique advisory ID(s) "
                f"across {summary['affected_packages']} affected package occurrence(s)."
            )
        else:
            print("No known vulnerabilities were reported for the scanned SBOM.")
        if evidence_path:
            try:
                rendered_path = evidence_path.relative_to(root).as_posix()
            except ValueError:
                rendered_path = str(evidence_path)
            print(f"Advisory evidence: {rendered_path}")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")

    if not result.scanner_succeeded:
        return 2
    return 1 if result.vulnerable else 0


def dispatch_security_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "audit":
        return None
    return audit_command(arguments[1:])
