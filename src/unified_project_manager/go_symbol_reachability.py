from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


GOVULNCHECK_PROTOCOL_VERSION = "v1.0.0"


class GoSymbolReachabilityError(ValueError):
    """Raised when govulncheck symbol evidence cannot be interpreted safely."""


@dataclass(frozen=True)
class GovulncheckConfig:
    protocol_version: str
    scanner_name: str | None
    scanner_version: str | None
    database: str
    database_last_modified: str | None
    go_version: str | None
    scan_level: str
    scan_mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GovulncheckModule:
    path: str
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GovulncheckSBOM:
    go_version: str | None
    modules: tuple[GovulncheckModule, ...]
    roots: tuple[str, ...]

    def has_module(self, path: str, version: str) -> bool:
        return any(module.path == path and module.version == version for module in self.modules)

    def to_dict(self) -> dict[str, Any]:
        return {
            "go_version": self.go_version,
            "modules": [module.to_dict() for module in self.modules],
            "roots": list(self.roots),
        }


@dataclass(frozen=True)
class GovulncheckFrame:
    module: str
    version: str | None
    package: str | None
    function: str | None
    receiver: str | None
    position: dict[str, Any] | None

    @property
    def symbol(self) -> str | None:
        if not self.function:
            return None
        if self.receiver:
            return f"{self.receiver}.{self.function}"
        return self.function

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["symbol"] = self.symbol
        return data


@dataclass(frozen=True)
class GovulncheckFinding:
    osv: str
    fixed_version: str | None
    trace: tuple[GovulncheckFrame, ...]

    @property
    def level(self) -> str:
        if self.trace and self.trace[0].function:
            return "symbol"
        if self.trace and self.trace[0].package:
            return "package"
        return "module"

    @property
    def vulnerable_frame(self) -> GovulncheckFrame | None:
        return self.trace[0] if self.trace else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "osv": self.osv,
            "fixed_version": self.fixed_version,
            "level": self.level,
            "trace": [frame.to_dict() for frame in self.trace],
        }


@dataclass(frozen=True)
class GovulncheckReport:
    config: GovulncheckConfig
    aliases: dict[str, tuple[str, ...]]
    findings: tuple[GovulncheckFinding, ...]
    sbom: GovulncheckSBOM | None = None

    @property
    def symbol_findings(self) -> tuple[GovulncheckFinding, ...]:
        return tuple(finding for finding in self.findings if finding.level == "symbol")

    def advisory_ids(self, osv_id: str) -> tuple[str, ...]:
        values = {osv_id, *self.aliases.get(osv_id, ())}
        return tuple(sorted(values))

    def matches_advisory(self, osv_id: str, advisory_id: str) -> bool:
        return advisory_id in self.advisory_ids(osv_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "sbom": self.sbom.to_dict() if self.sbom is not None else None,
            "aliases": {key: list(value) for key, value in sorted(self.aliases.items())},
            "findings": [finding.to_dict() for finding in self.findings],
            "symbol_findings": [finding.to_dict() for finding in self.symbol_findings],
        }


@dataclass(frozen=True)
class GovulncheckSymbolPlan:
    cwd: Path
    database: Path
    database_uri: str
    argv: tuple[str, ...]
    environment: dict[str, str]
    telemetry_mode_required: str = "off"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cwd": str(self.cwd),
            "database": str(self.database),
            "database_uri": self.database_uri,
            "argv": list(self.argv),
            "environment": dict(self.environment),
            "telemetry_mode_required": self.telemetry_mode_required,
            "network": "disabled-by-local-db-and-go-environment",
            "project_mutation": "not-planned",
            "interpretation": (
                "pre-public govulncheck source/symbol plan; symbol findings are static call-graph evidence, "
                "not runtime/data-flow reachability or exploitability"
            ),
        }


def _decode_stream(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    index = 0
    messages: list[dict[str, Any]] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise GoSymbolReachabilityError(f"Could not parse govulncheck JSON stream: {exc}") from exc
        if not isinstance(value, dict):
            raise GoSymbolReachabilityError("govulncheck JSON stream contained a non-object message")
        messages.append(value)
    return messages


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_config(value: object) -> GovulncheckConfig:
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck config message is not an object")
    protocol = value.get("protocol_version")
    if protocol != GOVULNCHECK_PROTOCOL_VERSION:
        raise GoSymbolReachabilityError(
            f"Unsupported govulncheck protocol version: {protocol!r}; expected {GOVULNCHECK_PROTOCOL_VERSION}"
        )

    scan_mode = value.get("scan_mode")
    if scan_mode != "source":
        raise GoSymbolReachabilityError(
            f"govulncheck stream is not explicit source-mode evidence: {scan_mode!r}"
        )
    scan_level = value.get("scan_level")
    if scan_level != "symbol":
        raise GoSymbolReachabilityError(
            f"govulncheck stream is not explicit symbol-level evidence: {scan_level!r}"
        )
    database = value.get("db")
    if not isinstance(database, str) or not database.startswith("file://"):
        raise GoSymbolReachabilityError(
            f"govulncheck stream is not backed by an explicit local file database: {database!r}"
        )

    return GovulncheckConfig(
        protocol_version=protocol,
        scanner_name=_optional_string(value.get("scanner_name")),
        scanner_version=_optional_string(value.get("scanner_version")),
        database=database,
        database_last_modified=_optional_string(value.get("db_last_modified")),
        go_version=_optional_string(value.get("go_version")),
        scan_level=scan_level,
        scan_mode=scan_mode,
    )


def _parse_sbom_module(value: object) -> GovulncheckModule:
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck SBOM modules must be objects")
    path = value.get("path")
    if not isinstance(path, str) or not path:
        raise GoSymbolReachabilityError("govulncheck SBOM module is missing path identity")
    return GovulncheckModule(path=path, version=_optional_string(value.get("version")))


def _parse_sbom(value: object) -> GovulncheckSBOM:
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck SBOM message is not an object")
    modules_value = value.get("modules", [])
    if not isinstance(modules_value, list):
        raise GoSymbolReachabilityError("govulncheck SBOM modules are not an array")
    roots_value = value.get("roots", [])
    if not isinstance(roots_value, list) or not all(isinstance(root, str) and root for root in roots_value):
        raise GoSymbolReachabilityError("govulncheck SBOM roots are not a non-empty-string array")
    modules = tuple(sorted(
        (_parse_sbom_module(module) for module in modules_value),
        key=lambda module: (module.path, module.version or ""),
    ))
    roots = tuple(sorted(set(roots_value)))
    if not roots:
        raise GoSymbolReachabilityError("govulncheck source scan SBOM has no root packages")
    return GovulncheckSBOM(
        go_version=_optional_string(value.get("go_version")),
        modules=modules,
        roots=roots,
    )


def _parse_position(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck frame position is not an object")

    allowed = {"filename", "offset", "line", "column"}
    unknown = set(value) - allowed
    if unknown:
        raise GoSymbolReachabilityError(
            "govulncheck frame position contains unsupported field(s): "
            + ", ".join(sorted(unknown))
        )

    position: dict[str, Any] = {}
    if "filename" in value:
        filename = value.get("filename")
        if not isinstance(filename, str) or not filename:
            raise GoSymbolReachabilityError(
                "govulncheck frame position filename must be a non-empty string when present"
            )
        position["filename"] = filename

    for name in ("offset", "line", "column"):
        if name not in value:
            raise GoSymbolReachabilityError(
                f"govulncheck frame position is missing required {name}"
            )
        item = value.get(name)
        if not isinstance(item, int) or isinstance(item, bool):
            raise GoSymbolReachabilityError(
                f"govulncheck frame position {name} is not an integer"
            )
        if name == "offset" and item < 0:
            raise GoSymbolReachabilityError(
                "govulncheck frame position offset must be >= 0"
            )
        if name == "line" and item <= 0:
            raise GoSymbolReachabilityError(
                "govulncheck frame position line must be > 0"
            )
        if name == "column" and item < 0:
            raise GoSymbolReachabilityError(
                "govulncheck frame position column must be >= 0"
            )
        position[name] = item
    return position


def _parse_frame(value: object) -> GovulncheckFrame:
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck finding trace contained a non-object frame")
    module = value.get("module")
    if not isinstance(module, str) or not module:
        raise GoSymbolReachabilityError("govulncheck finding frame is missing module identity")
    return GovulncheckFrame(
        module=module,
        version=_optional_string(value.get("version")),
        package=_optional_string(value.get("package")),
        function=_optional_string(value.get("function")),
        receiver=_optional_string(value.get("receiver")),
        position=_parse_position(value.get("position")),
    )


def _parse_finding(value: object) -> GovulncheckFinding:
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck finding message is not an object")
    osv = value.get("osv")
    if not isinstance(osv, str) or not osv:
        raise GoSymbolReachabilityError("govulncheck finding is missing an OSV identifier")
    trace_value = value.get("trace", [])
    if not isinstance(trace_value, list):
        raise GoSymbolReachabilityError("govulncheck finding trace is not an array")
    return GovulncheckFinding(
        osv=osv,
        fixed_version=_optional_string(value.get("fixed_version")),
        trace=tuple(_parse_frame(frame) for frame in trace_value),
    )


def _parse_osv_aliases(value: object) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise GoSymbolReachabilityError("govulncheck OSV message is not an object")
    osv_id = value.get("id")
    if not isinstance(osv_id, str) or not osv_id:
        raise GoSymbolReachabilityError("govulncheck OSV message is missing its id")
    aliases = value.get("aliases", [])
    if aliases is None:
        aliases = []
    if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
        raise GoSymbolReachabilityError("govulncheck OSV aliases are not a string array")
    return osv_id, tuple(sorted(set(item for item in aliases if item)))


def parse_govulncheck_symbol_stream(text: str) -> GovulncheckReport:
    """Parse offline govulncheck v1 source/symbol JSON without flattening levels.

    UPM requires the native scan SBOM for source-symbol evidence so findings can
    be checked against govulncheck's own declared Go version, module build list,
    and root package set. Module-, package-, and symbol-level findings remain
    distinct; only first-frame functions are called-symbol evidence.
    """

    messages = _decode_stream(text)
    if not messages:
        raise GoSymbolReachabilityError("govulncheck JSON stream is empty")
    first = messages[0]
    if set(first) != {"config"}:
        raise GoSymbolReachabilityError("govulncheck config must be the first and only field in the first message")
    config = _parse_config(first["config"])

    aliases: dict[str, tuple[str, ...]] = {}
    findings: list[GovulncheckFinding] = []
    sbom: GovulncheckSBOM | None = None
    allowed_fields = {"config", "progress", "SBOM", "osv", "finding"}
    for index, message in enumerate(messages[1:], start=2):
        populated = [key for key in allowed_fields if key in message and message[key] is not None]
        unknown = set(message) - allowed_fields
        if unknown:
            raise GoSymbolReachabilityError(
                f"govulncheck message {index} contains unsupported field(s): {', '.join(sorted(unknown))}"
            )
        if len(populated) != 1:
            raise GoSymbolReachabilityError(
                f"govulncheck message {index} must contain exactly one populated protocol field"
            )
        field = populated[0]
        if field == "config":
            raise GoSymbolReachabilityError("govulncheck stream contained more than one config message")
        if field == "SBOM":
            if sbom is not None:
                raise GoSymbolReachabilityError("govulncheck stream contained more than one SBOM message")
            sbom = _parse_sbom(message[field])
        elif field == "osv":
            osv_id, osv_aliases = _parse_osv_aliases(message[field])
            aliases[osv_id] = osv_aliases
        elif field == "finding":
            findings.append(_parse_finding(message[field]))

    if sbom is None:
        raise GoSymbolReachabilityError("govulncheck source-symbol stream is missing its scan SBOM")

    return GovulncheckReport(
        config=config,
        aliases=dict(sorted(aliases.items())),
        findings=tuple(findings),
        sbom=sbom,
    )


def build_govulncheck_symbol_plan(
    cwd: str | Path,
    local_database: str | Path,
    *,
    executable: str = "govulncheck",
) -> GovulncheckSymbolPlan:
    """Build an offline, pre-public govulncheck symbol-analysis plan.

    The caller must separately verify that Go telemetry mode is already `off`.
    UPM intentionally does not mutate the user's telemetry configuration merely
    to execute this provider.
    """

    project = Path(cwd).expanduser().resolve()
    database = Path(local_database).expanduser().resolve()
    if not project.is_dir():
        raise GoSymbolReachabilityError(f"Go symbol-analysis cwd is not a directory: {project}")
    if not database.is_dir():
        raise GoSymbolReachabilityError(f"Go vulnerability database is not a directory: {database}")
    if not executable:
        raise GoSymbolReachabilityError("govulncheck executable name/path is empty")

    database_uri = database.as_uri()
    return GovulncheckSymbolPlan(
        cwd=project,
        database=database,
        database_uri=database_uri,
        argv=(
            executable,
            "-format", "json",
            "-mode", "source",
            "-scan", "symbol",
            "-db", database_uri,
            "./...",
        ),
        environment={
            "GOPROXY": "off",
            "GOWORK": "off",
            "GOSUMDB": "off",
            "GOTOOLCHAIN": "local",
            "GOENV": "off",
            "GOFLAGS": os.environ.get("GOFLAGS", ""),
            "GOROOT": os.environ.get("GOROOT", ""),
        },
    )


def validate_govulncheck_telemetry_mode(mode: str) -> None:
    """Require telemetry to be disabled before subprocess execution is allowed."""
    if mode != "off":
        raise GoSymbolReachabilityError(
            "govulncheck symbol analysis requires Go telemetry mode 'off'; "
            "UPM will not change the user's telemetry configuration automatically"
        )
