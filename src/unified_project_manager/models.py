from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["info", "warning", "error"]


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

    def to_dict(self, root: Path) -> dict[str, Any]:
        data = asdict(self)
        relative = self.path.relative_to(root)
        data["path"] = "." if str(relative) == "." else relative.as_posix()
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
            "summary": {"errors": self.errors, "warnings": self.warnings},
            "findings": [finding.to_dict() for finding in self.findings],
        }
