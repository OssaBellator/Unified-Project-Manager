from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from support_go_symbol_runtime_fixture import (
    FIXTURE_MODULE,
    FIXTURE_VERSION,
    fixture_go_environment,
    prepare_module_cache,
    write_runtime_fixture,
)
from support_go_symbol_side_effects import diff_named_roots, snapshot_named_roots
from support_go_vulndb_fixture import FIXTURE_ALIAS, FIXTURE_ID, FIXTURE_SYMBOL
from unified_project_manager.go_symbol_build_selection import compare_go_symbol_build_selection
from unified_project_manager.go_symbol_correlation import correlate_govulncheck_symbols
from unified_project_manager.go_symbol_frame_source_alignment import (
    compare_positioned_govulncheck_frame_to_source_observation,
)
from unified_project_manager.go_symbol_execution import execute_govulncheck_symbol
from unified_project_manager.go_symbol_preflight import preflight_govulncheck_symbol
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan
from unified_project_manager.go_symbol_scan_alignment import compare_go_symbol_observation_to_scan_sbom
from unified_project_manager.go_symbol_source_observation import (
    build_go_symbol_source_observation_plan,
    execute_go_symbol_source_observation,
)


def _emit(payload: dict[str, object], code: int) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


def _prerequisites() -> tuple[dict[str, object], list[str]]:
    go = shutil.which("go")
    govulncheck = shutil.which("govulncheck")
    telemetry = None
    telemetry_returncode = None
    reasons: list[str] = []
    if not go:
        reasons.append("Go executable is not available")
    if not govulncheck:
        reasons.append("govulncheck executable is not available; this command does not install it")
    if go:
        completed = subprocess.run([go, "env", "GOTELEMETRY"], text=True, capture_output=True, check=False)
        telemetry_returncode = completed.returncode
        if completed.returncode != 0:
            reasons.append("could not inspect existing Go telemetry mode")
        else:
            telemetry = (completed.stdout or "").strip()
            if telemetry != "off":
                reasons.append(
                    f"Go telemetry mode is {telemetry!r}, not 'off'; this command does not change it"
                )
    return {
        "go": go,
        "govulncheck": govulncheck,
        "go_telemetry": telemetry,
        "go_telemetry_query_returncode": telemetry_returncode,
    }, reasons


def _dependency_impact() -> dict[str, object]:
    return {
        "advisory_id": FIXTURE_ALIAS,
        "ecosystem": "Go",
        "package": FIXTURE_MODULE,
        "version": FIXTURE_VERSION,
        "provider": "go-modules",
        "scope": "module-requirement",
        "component": ".:go",
        "paths": [["example.com/app", FIXTURE_MODULE]],
        "evidence": {"module": FIXTURE_MODULE, "effective_name": FIXTURE_MODULE},
    }


def _roots(fixture) -> dict[str, Path]:
    return {
        "project": fixture.project,
        "local_module_proxy": fixture.proxy,
        "local_vulnerability_db": fixture.vulnerability_db,
        "go_module_cache": fixture.module_cache,
        "go_build_cache": fixture.build_cache,
    }


def _deltas(before, after) -> dict[str, dict[str, object]]:
    return {name: delta.to_dict() for name, delta in diff_named_roots(before, after).items()}


def _changed(deltas: dict[str, dict[str, object]]) -> list[str]:
    return sorted(name for name, value in deltas.items() if value["changed"])


def main() -> int:
    prerequisites, reasons = _prerequisites()
    if reasons:
        return _emit({
            "status": "blocked",
            "prerequisites": prerequisites,
            "reasons": reasons,
            "interpretation": "Prerequisite-dependent characterization did not run; blocked is not a pass.",
        }, 2)

    go = str(prerequisites["go"])
    govulncheck = str(prerequisites["govulncheck"])
    with tempfile.TemporaryDirectory() as temporary:
        fixture = write_runtime_fixture(Path(temporary) / "fixture")
        prepared = prepare_module_cache(fixture, go_executable=go)
        if prepared.returncode != 0:
            return _emit({
                "status": "failed",
                "phase": "fixture-preparation",
                "returncode": prepared.returncode,
                "stderr": (prepared.stderr or "").strip(),
                "stdout": (prepared.stdout or "").strip(),
            }, 1)

        roots = _roots(fixture)
        baseline = snapshot_named_roots(roots)
        isolated = fixture_go_environment(fixture)
        inherited = {"GOMODCACHE": isolated["GOMODCACHE"], "GOCACHE": isolated["GOCACHE"]}
        with patch.dict(os.environ, inherited, clear=False):
            observation_plan = build_go_symbol_source_observation_plan(fixture.project, executable=go)
            observation = execute_go_symbol_source_observation(observation_plan)
            after_observation = snapshot_named_roots(roots)
            observation_delta = _deltas(baseline, after_observation)
            if not observation.succeeded:
                return _emit({
                    "status": "failed",
                    "phase": "source-observation",
                    "execution": observation.to_dict(),
                    "side_effects": observation_delta,
                }, 1)

            symbol_plan = build_govulncheck_symbol_plan(
                fixture.project, fixture.vulnerability_db, executable=govulncheck
            )
            planned = compare_go_symbol_build_selection(symbol_plan, observation_plan)
            if not planned.matches:
                return _emit({
                    "status": "failed",
                    "phase": "planned-build-selection-alignment",
                    "planned_alignment": planned.to_dict(),
                    "side_effects": observation_delta,
                }, 1)

            preflight = preflight_govulncheck_symbol(symbol_plan)
            if not preflight.ready:
                return _emit({
                    "status": "blocked",
                    "phase": "govulncheck-preflight",
                    "preflight": preflight.to_dict(),
                    "side_effects": observation_delta,
                }, 2)
            execution = execute_govulncheck_symbol(symbol_plan, preflight=preflight)
            after_scan = snapshot_named_roots(roots)

        scanner_delta = _deltas(after_observation, after_scan)
        combined_delta = _deltas(baseline, after_scan)
        side_effects = {
            "baseline": "after local file-proxy module-cache preparation",
            "source_observation": observation_delta,
            "govulncheck": scanner_delta,
            "combined": combined_delta,
            "changed_roots": {
                "source_observation": _changed(observation_delta),
                "govulncheck": _changed(scanner_delta),
                "combined": _changed(combined_delta),
            },
            "observed_non_project_roots": [
                "local_module_proxy",
                "local_vulnerability_db",
                "go_module_cache",
                "go_build_cache",
            ],
            "outside_observed_roots": "not-observed",
            "non_project_cache_tool_mutation": (
                "characterized only for the isolated roots above; other user/tool state side effects remain possible"
            ),
        }
        if not execution.succeeded:
            return _emit({
                "status": "failed",
                "phase": "govulncheck-execution",
                "execution": execution.to_dict(),
                "side_effects": side_effects,
            }, 1)

        alignment = compare_go_symbol_observation_to_scan_sbom(observation.observation, execution.report)
        correlation = correlate_govulncheck_symbols(
            execution.report, [_dependency_impact()], component=".:go"
        )
        synthetic_findings = tuple(
            finding
            for finding in execution.report.symbol_findings
            if finding.osv == FIXTURE_ID
            and finding.vulnerable_frame is not None
            and finding.vulnerable_frame.symbol == FIXTURE_SYMBOL
            and finding.vulnerable_frame.module == FIXTURE_MODULE
            and finding.vulnerable_frame.version == FIXTURE_VERSION
        )
        synthetic_finding = len(synthetic_findings) == 1
        frame_source_alignment = None
        if synthetic_finding:
            frame_source_alignment = compare_positioned_govulncheck_frame_to_source_observation(
                synthetic_findings[0].vulnerable_frame,
                observation.observation,
            )
        immutable = [
            label
            for label in ("project", "local_module_proxy", "local_vulnerability_db")
            if combined_delta[label]["changed"]
        ]
        failures: list[str] = []
        if immutable:
            failures.append("immutable validation roots changed: " + ", ".join(immutable))
        if not alignment.declared_inventory_match:
            failures.append("real scanner SBOM does not align with the Go-native declared inventory")
        if not synthetic_finding:
            failures.append("real scanner stream does not contain exactly one expected synthetic vulnerable symbol")
        elif frame_source_alignment is None or not frame_source_alignment.matched:
            failures.append("expected synthetic vulnerable frame does not correspond to the observed package/syntax file")
        if len(correlation.matches) != 1 or correlation.unmatched:
            failures.append("real scanner stream did not produce exactly one strict UPM correlation")

        return _emit({
            "status": "failed" if failures else "ok",
            "prerequisites": prerequisites,
            "checks": {
                "planned_build_selection_matches": planned.matches,
                "declared_inventory_match": alignment.declared_inventory_match,
                "synthetic_symbol_finding": synthetic_finding,
                "positioned_frame_source_match": (
                    frame_source_alignment.matched if frame_source_alignment is not None else False
                ),
                "strict_correlation_matches": len(correlation.matches),
                "strict_correlation_unmatched": len(correlation.unmatched),
                "immutable_root_changes": immutable,
            },
            "alignment": alignment.to_dict(),
            "frame_source_correspondence": (
                frame_source_alignment.to_dict() if frame_source_alignment is not None else None
            ),
            "side_effects": side_effects,
            "public": False,
            "persisted": False,
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "failures": failures,
        }, 1 if failures else 0)


if __name__ == "__main__":
    sys.exit(main())
