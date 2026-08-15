from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit_status import evaluate_audit_status
from .cache_coverage import cache_integrity_coverage
from .doctor import diagnose
from .models import ProjectGraph
from .verifier import plan_native_verification


class PolicyError(ValueError):
    """Raised when UPM policy configuration is invalid."""


@dataclass(frozen=True)
class PolicyConfig:
    require_lockfiles: bool = False
    require_integrity_snapshot: bool = False
    require_native_verification: bool = False
    require_cache_integrity_verification: bool = False
    require_advisory_evidence: bool = False
    allowed_managers: tuple[str, ...] = ()
    denied_managers: tuple[str, ...] = ()
    max_warnings: int | None = None
    max_errors: int | None = None
    max_advisory_age_seconds: int | None = None
    max_known_vulnerabilities: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_managers"] = list(self.allowed_managers)
        data["denied_managers"] = list(self.denied_managers)
        return data


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str
    component: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyReport:
    root: Path
    config: PolicyConfig
    violations: list[PolicyViolation] = field(default_factory=list)
    doctor_errors: int = 0
    doctor_warnings: int = 0

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "passed": self.passed,
            "config": self.config.to_dict(),
            "doctor": {"errors": self.doctor_errors, "warnings": self.doctor_warnings},
            "violations": [item.to_dict() for item in self.violations],
        }


def _string_list(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PolicyError(f"upm.toml policy.{field_name} must be an array of non-empty strings.")
    return tuple(dict.fromkeys(value))


def _optional_non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PolicyError(f"upm.toml policy.{field_name} must be a non-negative integer.")
    return value


def load_policy(root: str | Path) -> PolicyConfig:
    root_path = Path(root).expanduser().resolve()
    path = root_path / "upm.toml"
    if not path.is_file():
        return PolicyConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"Could not read {path}: {exc}") from exc
    value = data.get("policy")
    if value is None:
        return PolicyConfig()
    if not isinstance(value, dict):
        raise PolicyError("upm.toml [policy] must be a table.")

    bool_fields: dict[str, bool] = {}
    for name in (
        "require_lockfiles",
        "require_integrity_snapshot",
        "require_native_verification",
        "require_cache_integrity_verification",
        "require_advisory_evidence",
    ):
        raw = value.get(name, False)
        if not isinstance(raw, bool):
            raise PolicyError(f"upm.toml policy.{name} must be a boolean.")
        bool_fields[name] = raw

    max_warnings = _optional_non_negative_int(value.get("max_warnings"), "max_warnings")
    max_errors = _optional_non_negative_int(value.get("max_errors"), "max_errors")
    max_advisory_age_seconds = _optional_non_negative_int(value.get("max_advisory_age_seconds"), "max_advisory_age_seconds")
    max_known_vulnerabilities = _optional_non_negative_int(value.get("max_known_vulnerabilities"), "max_known_vulnerabilities")

    allowed = _string_list(value.get("allowed_managers"), "allowed_managers")
    denied = _string_list(value.get("denied_managers"), "denied_managers")
    overlap = sorted(set(allowed) & set(denied))
    if overlap:
        raise PolicyError("Managers cannot be both allowed and denied: " + ", ".join(overlap))

    return PolicyConfig(
        require_lockfiles=bool_fields["require_lockfiles"],
        require_integrity_snapshot=bool_fields["require_integrity_snapshot"],
        require_native_verification=bool_fields["require_native_verification"],
        require_cache_integrity_verification=bool_fields["require_cache_integrity_verification"],
        require_advisory_evidence=bool_fields["require_advisory_evidence"],
        allowed_managers=allowed,
        denied_managers=denied,
        max_warnings=max_warnings,
        max_errors=max_errors,
        max_advisory_age_seconds=max_advisory_age_seconds,
        max_known_vulnerabilities=max_known_vulnerabilities,
    )


def evaluate_policy(graph: ProjectGraph, *, deep: bool = False) -> PolicyReport:
    config = load_policy(graph.root)
    doctor = diagnose(graph, deep=deep)
    report = PolicyReport(graph.root, config, doctor_errors=doctor.errors, doctor_warnings=doctor.warnings)

    for component in graph.components:
        key = component.key(graph.root)
        manager = component.manager
        if config.require_lockfiles and not component.lockfiles:
            report.violations.append(PolicyViolation(
                "policy.lockfile-required",
                "Component has no discovered native lock/checksum state file.",
                key,
            ))
        if config.allowed_managers and manager not in config.allowed_managers:
            report.violations.append(PolicyViolation(
                "policy.manager-not-allowed",
                f"Manager {manager or 'unknown'!r} is not in the allowed manager set.",
                key,
            ))
        if manager and manager in config.denied_managers:
            report.violations.append(PolicyViolation(
                "policy.manager-denied",
                f"Manager {manager!r} is denied by project policy.",
                key,
            ))

    if config.require_integrity_snapshot and not (graph.root / ".upm" / "state.json").is_file():
        report.violations.append(PolicyViolation(
            "policy.snapshot-required",
            "Project policy requires a .upm/state.json integrity snapshot.",
        ))

    if config.require_native_verification:
        plans, skips = plan_native_verification(graph)
        planned = {plan.component for plan in plans}
        for skip in skips:
            if skip.component not in planned:
                report.violations.append(PolicyViolation(
                    "policy.native-verification-required",
                    f"No configured non-mutating native verifier: {skip.reason}",
                    skip.component,
                ))

    if config.require_cache_integrity_verification:
        for item in cache_integrity_coverage(graph):
            if not item.supported:
                report.violations.append(PolicyViolation(
                    "policy.cache-integrity-verification-required",
                    f"No configured authoritative cache-integrity path: {item.reason}",
                    item.component,
                ))

    if config.require_advisory_evidence or config.max_advisory_age_seconds is not None or config.max_known_vulnerabilities is not None:
        advisory = evaluate_audit_status(graph, max_age_seconds=config.max_advisory_age_seconds)
        if config.require_advisory_evidence and not advisory.current:
            report.violations.append(PolicyViolation(
                "policy.advisory-evidence-required",
                f"Current local advisory evidence is required, but its state is {advisory.state!r}.",
            ))
        if config.max_known_vulnerabilities is not None:
            if not advisory.current:
                report.violations.append(PolicyViolation(
                    "policy.advisory-evidence-unavailable",
                    "Known-vulnerability budget cannot be evaluated without current local advisory evidence.",
                ))
            elif (advisory.vulnerabilities or 0) > config.max_known_vulnerabilities:
                report.violations.append(PolicyViolation(
                    "policy.advisory-budget-exceeded",
                    f"Persisted advisory evidence reports {advisory.vulnerabilities or 0} vulnerabilities; policy allows at most {config.max_known_vulnerabilities}.",
                ))

    if config.max_errors is not None and doctor.errors > config.max_errors:
        report.violations.append(PolicyViolation(
            "policy.error-budget-exceeded",
            f"Doctor reported {doctor.errors} errors; policy allows at most {config.max_errors}.",
        ))

    if config.max_warnings is not None and doctor.warnings > config.max_warnings:
        report.violations.append(PolicyViolation(
            "policy.warning-budget-exceeded",
            f"Doctor reported {doctor.warnings} warnings; policy allows at most {config.max_warnings}.",
        ))

    return report
