from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .fleet_policy import fleet_policy_summary, registered_policy_statuses
from .native_exec import NativeExecError, execute_native_exec, plan_native_exec
from .policy import PolicyError, evaluate_policy
from .registry import RegistryError
from .status import project_status


def _existing_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    return root


def _exec_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm exec",
        description="Preview or execute an arbitrary command through a component's authoritative native manager",
    )
    parser.add_argument("--path", default=".", help="Project root to discover")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or project/package name")
    parser.add_argument("--apply", action="store_true", help="Execute the command; otherwise preview it")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-command UPM doctor verification")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments passed to the authoritative native manager")
    return parser


def _projects_policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm projects policy", description="Evaluate project policy across registered repositories")
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument("--deep", action="store_true", help="Use deep installed-state doctor findings for warning budgets")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm policy", description="Evaluate cross-ecosystem project policy from upm.toml")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--deep", action="store_true", help="Use deep installed-state doctor findings for warning budgets")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _status_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm status", description="Summarize unified project state and persisted local evidence")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--deep", action="store_true", help="Include installed-environment doctor checks")
    parser.add_argument("--storage", action="store_true", help="Measure known local package/environment/build storage")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def exec_command(argv: list[str]) -> int:
    args = _exec_parser().parse_args(argv)
    manager_args = list(args.arguments)
    if manager_args and manager_args[0] == "--":
        manager_args = manager_args[1:]
    try:
        root = _existing_root(args.path)
        graph = discover(root)
        plan = plan_native_exec(graph, manager_args, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, NativeExecError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        payload = {"executed": False, "plan": plan.to_dict(root)}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Directory: {plan.to_dict(root)['cwd']}")
            print(f"Command:   {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute through the native manager.")
        return 0

    result = execute_native_exec(plan, root, verify=not args.no_verify)
    if args.as_json:
        print(json.dumps(result.to_dict(root), indent=2, sort_keys=True))
    else:
        print(f"Component: {plan.component} ({plan.manager})")
        print(f"Command: {shlex.join(plan.argv)}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.verification:
            print(
                f"Post-command health: {result.verification.health_score}% "
                f"({result.verification.errors} errors, {result.verification.warnings} warnings)"
            )
    if result.returncode != 0:
        return result.returncode if 0 < result.returncode < 126 else 1
    return 1 if result.verification and result.verification.errors else 0


def projects_policy_command(argv: list[str]) -> int:
    args = _projects_policy_parser().parse_args(argv)
    try:
        statuses = registered_policy_statuses(args.registry, deep=args.deep)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    summary = fleet_policy_summary(statuses)
    if args.as_json:
        print(json.dumps({"summary": summary, "projects": statuses}, indent=2, sort_keys=True))
    elif not statuses:
        print("No projects registered.")
    else:
        for item in statuses:
            symbol = "✓" if item["passed"] else "x"
            if item.get("error"):
                print(f"{symbol} {item['path']}: {item['error']}")
            else:
                violations = len(item["report"]["violations"])
                print(f"{symbol} {item['path']}: {violations} policy violation(s)")
        print(f"Fleet policy: {summary['passed']}/{summary['projects']} passed")
    return 0 if summary["failed"] == 0 else 1


def policy_command(argv: list[str]) -> int:
    args = _policy_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        report = evaluate_policy(discover(root), deep=args.deep)
    except (FileNotFoundError, NotADirectoryError, OSError, PolicyError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    elif report.passed:
        print("Policy: passed")
    else:
        print(f"Policy: {len(report.violations)} violation(s)")
        for violation in report.violations:
            location = f" [{violation.component}]" if violation.component else ""
            print(f"x {violation.code}{location}: {violation.message}")
    return 0 if report.passed else 1


def status_command(argv: list[str]) -> int:
    args = _status_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        data = project_status(discover(root), deep=args.deep, include_storage=args.storage)
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        summary = data["summary"]
        health = data["health"]
        coverage = data["native_verification"]["coverage"]
        ecosystems = ", ".join(summary["ecosystems"]) or "none"
        managers = ", ".join(summary["managers"]) or "none"
        print(f"Project: {data['root']}")
        print(
            f"Health: {health['health_score']}% "
            f"({health['summary']['errors']} errors, {health['summary']['warnings']} warnings)"
        )
        print(
            f"Components: {summary['components']} | workspaces: {summary['workspaces']} | "
            f"ecosystems: {ecosystems} | managers: {managers}"
        )
        print(
            f"Dependencies: {summary['direct_dependencies']} direct | "
            f"{summary['resolved_packages']} resolved observations"
        )
        snapshot = "present" if data["integrity_snapshot"]["exists"] else "absent"
        print(f"Integrity snapshot: {snapshot} ({data['integrity_snapshot']['path']})")
        print(
            "Native verification coverage: "
            f"{coverage['planned_components']}/{coverage['total_components']} plannable"
        )
        providers = data["relationship_providers"]
        print(
            "Relationship provider coverage: "
            f"{providers['supported_components']}/{providers['total_components']} supported"
        )
        advisory = data["advisory_evidence"]
        advisory_detail = advisory["state"]
        if advisory.get("vulnerabilities") is not None:
            advisory_detail += f" ({advisory['vulnerabilities']} vulnerabilities)"
        print(f"Advisory evidence: {advisory_detail}")
        receipts = data["mutation_receipts"]
        receipt_detail = receipts["state"]
        if receipts.get("changes"):
            receipt_detail += f" ({len(receipts['changes'])} state changes)"
        print(f"Mutation receipts: {receipt_detail}")
        chain = data["mutation_receipt_chain"]
        if chain.get("present") is False:
            print("Receipt chain: absent (optional)")
        else:
            chain_detail = "valid" if chain.get("valid") else "invalid"
            anchor = chain.get("anchor_digest")
            if anchor:
                chain_detail += f" (anchor {anchor})"
            print(f"Receipt chain: {chain_detail}")
        local_summary = data["local_evidence"]["summary"]
        if local_summary["workspace_errors"] or local_summary["workspace_warnings"]:
            print(
                "Workspace health: "
                f"{local_summary['workspace_errors']} errors, {local_summary['workspace_warnings']} warnings"
            )
        policy = data["policy"]
        print("Policy: passed" if policy["passed"] else f"Policy: {len(policy['violations'])} violation(s)")
        if summary["blockers"]:
            print("Blockers: " + ", ".join(summary["blockers"]))
        if data["storage"] is not None:
            total = data["storage"]["summary"]["bytes"]
            print(f"Known local artifact storage: {total / (1024 * 1024):.2f} MiB")
    return 1 if data["summary"]["blockers"] else 0


def dispatch_control_command(arguments: list[str]) -> int | None:
    if not arguments:
        return None
    if arguments[0] == "exec":
        return exec_command(arguments[1:])
    if arguments[0] == "status":
        return status_command(arguments[1:])
    if arguments[0] == "policy":
        return policy_command(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "projects" and arguments[1] == "policy":
        return projects_policy_command(arguments[2:])
    return None
