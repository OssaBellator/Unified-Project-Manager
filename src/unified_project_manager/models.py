from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["info", "warning", "error"]
Operation = Literal["init", "install", "sync", "add", "remove"]


@dataclass(frozen=True)
class Dependency:
    name: str
    requirement: str | None = None
    scope: str = "runtime"


@dataclass(frozen=True)
class ToolchainRequirement:
    name: str
    requirement: str | None = None


@dataclass
class Component:
    ecosystem: str
    path: Path
    manager: str | None
    manifests: list[str] = field(default_factory=list)
    lockfiles: list[str] = field(default_factory=list)
    toolchains: list[ToolchainRequirement] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def key(self, root: Path) -> str:
        relative = self.path.relative_to(root)
        location = "." if str(relative) == "." else relative.as_posix()
        return f"{location}:{self.ecosystem}"

    def relative_path(self, root: Path) -> str:
        relative = self.path.relative_to(root)
        return "." if str(relative) == "." else relative.as_posix()

    def to_dict(self, root: Path) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = self.relative_path(root)
        data["key"] = self.key(root)
        return data


@dataclass
class ProjectGraph:
    root: Path
    components: list[Component] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "components": [component.to_dict(self.root) for component in self.components],
        }


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    component: str | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    root: Path
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(item.severity == "error" for item in self.findings)

    @property
    def warnings(self) -> int:
        return sum(item.severity == "warning" for item in self.findings)

    @property
    def infos(self) -> int:
        return sum(item.severity == "info" for item in self.findings)

    @property
    def health_score(self) -> int:
        return max(0, 100 - (self.errors * 20) - (self.warnings * 5))

    @property
    def healthy(self) -> bool:
        return self.errors == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "healthy": self.healthy,
            "health_score": self.health_score,
            "summary": {"errors": self.errors, "warnings": self.warnings, "infos": self.infos},
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class CommandPlan:
    operation: Operation
    component: str
    manager: str
    argv: tuple[str, ...]
    cwd: Path
    packages: tuple[str, ...] = ()

    def to_dict(self, root: Path) -> dict[str, Any]:
        try:
            cwd = self.cwd.relative_to(root).as_posix() or "."
        except ValueError:
            cwd = str(self.cwd)
        return {
            "operation": self.operation,
            "component": self.component,
            "manager": self.manager,
            "argv": list(self.argv),
            "cwd": cwd,
            "packages": list(self.packages),
        }


@dataclass
class CommandResult:
    plan: CommandPlan
    executed: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    verification: DoctorReport | None = None

    @property
    def succeeded(self) -> bool:
        return self.executed and self.returncode == 0 and (self.verification is None or self.verification.errors == 0)

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "executed": self.executed,
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "verification": self.verification.to_dict() if self.verification else None,
        }
