from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class GoSymbolSourceObservationError(ValueError):
    """Raised when candidate Go source/build observation cannot be trusted."""


MIN_LOADER_PROFILE_GO_MINOR = 21

BUILD_ENV_KEYS = (
    "GOOS",
    "GOARCH",
    "GOVERSION",
    "CGO_ENABLED",
    "GOFLAGS",
    "GOEXPERIMENT",
    "GOAMD64",
    "GOARM64",
    "GOARM",
    "GO386",
    "GOMIPS",
    "GOMIPS64",
    "GOPPC64",
    "GORISCV64",
    "GOWASM",
    "CC",
    "CXX",
    "PKG_CONFIG",
    "CGO_CFLAGS",
    "CGO_CPPFLAGS",
    "CGO_CXXFLAGS",
    "CGO_FFLAGS",
    "CGO_LDFLAGS",
)

SOURCE_FILE_FIELDS = (
    "GoFiles",
    "CgoFiles",
    "CFiles",
    "CXXFiles",
    "MFiles",
    "HFiles",
    "FFiles",
    "SFiles",
    "SwigFiles",
    "SwigCXXFiles",
    "SysoFiles",
    "EmbedFiles",
)

IGNORED_FILE_FIELDS = (
    "IgnoredGoFiles",
    "IgnoredOtherFiles",
)


@dataclass(frozen=True)
class GoSymbolSourceObservationPlan:
    cwd: Path
    env_argv: tuple[str, ...]
    packages_argv: tuple[str, ...]
    environment: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cwd": str(self.cwd),
            "env_argv": list(self.env_argv),
            "packages_argv": list(self.packages_argv),
            "environment": dict(self.environment),
            "minimum_loader_profile_go": f"1.{MIN_LOADER_PROFILE_GO_MINOR}",
            "network": "disabled-by-go-environment",
            "project_mutation": "none-planned",
            "non_project_cache_tool_mutation": "possible",
            "scope": "candidate-govulncheck-source-build-inputs",
            "freshness": "not-established",
            "govulncheck_equivalence": "not-established",
        }


@dataclass(frozen=True)
class GoSymbolBuildEnvironment:
    values: tuple[tuple[str, str], ...]

    def get(self, key: str) -> str | None:
        return dict(self.values).get(key)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.values}


@dataclass(frozen=True)
class GoSymbolModuleInput:
    path: str
    version: str | None
    main: bool
    effective_path: str
    effective_version: str | None

    @property
    def replaced(self) -> bool:
        return (self.path, self.version) != (self.effective_path, self.effective_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "replaced": self.replaced,
        }


@dataclass(frozen=True)
class GoSymbolPackageInput:
    import_path: str
    name: str | None
    standard: bool
    dep_only: bool
    directory: str
    module: GoSymbolModuleInput | None
    compiled_go_files: tuple[str, ...]
    source_files: tuple[tuple[str, tuple[str, ...]], ...]
    ignored_files: tuple[tuple[str, tuple[str, ...]], ...]
    imports: tuple[str, ...]

    @property
    def selected_files(self) -> tuple[str, ...]:
        """Return broad Go/native/embed build inputs selected by the Go command."""
        return tuple(sorted({
            file
            for _field, files in self.source_files
            for file in files
        }))

    @property
    def syntax_go_files(self) -> tuple[str, ...]:
        """Return the Go files the loader reports as suitable for type checking."""
        return self.compiled_go_files

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_path": self.import_path,
            "name": self.name,
            "standard": self.standard,
            "dep_only": self.dep_only,
            "directory": self.directory,
            "module": self.module.to_dict() if self.module is not None else None,
            "compiled_go_files": list(self.compiled_go_files),
            "syntax_go_files": list(self.syntax_go_files),
            "source_files": {field: list(files) for field, files in self.source_files},
            "ignored_files": {field: list(files) for field, files in self.ignored_files},
            "selected_files": list(self.selected_files),
            "imports": list(self.imports),
        }


@dataclass(frozen=True)
class GoSymbolSourceObservation:
    build_environment: GoSymbolBuildEnvironment
    packages: tuple[GoSymbolPackageInput, ...]

    @property
    def root_packages(self) -> tuple[str, ...]:
        return tuple(sorted(
            package.import_path
            for package in self.packages
            if not package.dep_only
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_environment": self.build_environment.to_dict(),
            "packages": [package.to_dict() for package in self.packages],
            "root_packages": list(self.root_packages),
            "scope": "candidate-govulncheck-source-build-inputs",
            "freshness": "not-established",
            "govulncheck_equivalence": "not-established",
            "source_state_fingerprint": False,
            "interpretation": (
                "Go-native package/source selection candidate only; compiled Go syntax inputs are retained "
                "separately from broader build inputs, but until compared with a real govulncheck source "
                "scan matching observations do not establish symbol-evidence freshness"
            ),
        }


@dataclass(frozen=True)
class GoSymbolSourceObservationExecution:
    plan: GoSymbolSourceObservationPlan
    returncode: int
    observation: GoSymbolSourceObservation | None
    stderr: str
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and self.observation is not None and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "stderr": self.stderr,
            "error": self.error,
            "plan": self.plan.to_dict(),
            "observation": self.observation.to_dict() if self.observation is not None else None,
            "public": False,
            "persisted": False,
        }


def build_go_symbol_source_observation_plan(
    cwd: str | Path,
    *,
    executable: str = "go",
) -> GoSymbolSourceObservationPlan:
    project = Path(cwd).expanduser().resolve()
    if not project.is_dir():
        raise GoSymbolSourceObservationError(
            f"Go source/build observation cwd is not a directory: {project}"
        )
    if not executable:
        raise GoSymbolSourceObservationError("Go executable name/path is empty")
    return GoSymbolSourceObservationPlan(
        cwd=project,
        env_argv=(executable, "env", "-json"),
        packages_argv=(
            executable,
            "list",
            "-e",
            "-mod=readonly",
            "-deps=true",
            "-compiled=true",
            "-test=false",
            "-export=false",
            "-find=false",
            "-buildvcs=false",
            "-pgo=off",
            "-json",
            "--",
            "./...",
        ),
        environment={
            "GOPROXY": "off",
            "GOWORK": "off",
            "GOSUMDB": "off",
            "GOTOOLCHAIN": "local",
        },
    )


def parse_go_symbol_build_environment(text: str) -> GoSymbolBuildEnvironment:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GoSymbolSourceObservationError(f"Could not parse `go env -json`: {exc}") from exc
    if not isinstance(value, dict):
        raise GoSymbolSourceObservationError("`go env -json` did not return an object")
    invalid = [
        key
        for key in BUILD_ENV_KEYS
        if key in value and not isinstance(value.get(key), str)
    ]
    if invalid:
        raise GoSymbolSourceObservationError(
            "`go env -json` contains non-string build inputs: " + ", ".join(invalid)
        )
    required = ("GOOS", "GOARCH", "GOVERSION")
    missing = [key for key in required if not isinstance(value.get(key), str) or not value.get(key)]
    if missing:
        raise GoSymbolSourceObservationError(
            "`go env -json` is missing required build identity: " + ", ".join(missing)
        )
    selected = tuple(
        (key, str(value[key]))
        for key in BUILD_ENV_KEYS
        if isinstance(value.get(key), str)
    )
    return GoSymbolBuildEnvironment(selected)


def _go_minor_version(version: str) -> int:
    """Extract the Go 1.x minor version from release or devel GOVERSION text."""
    match = re.search(r"(?:^|\s)go1\.(\d+)(?:\D|$)", version)
    if match is None:
        raise GoSymbolSourceObservationError(
            f"Could not interpret GOVERSION for candidate loader profile: {version!r}"
        )
    return int(match.group(1))


def validate_go_symbol_loader_profile_version(environment: GoSymbolBuildEnvironment) -> None:
    version = environment.get("GOVERSION")
    if version is None:
        raise GoSymbolSourceObservationError("candidate loader profile is missing GOVERSION")
    minor = _go_minor_version(version)
    if minor < MIN_LOADER_PROFILE_GO_MINOR:
        raise GoSymbolSourceObservationError(
            "candidate govulncheck source/build observation requires Go 1.21+ to mirror "
            f"the normalized go/packages loader profile; observed {version!r}"
        )


def _decode_json_stream(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    index = 0
    values: list[dict[str, Any]] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise GoSymbolSourceObservationError(f"Could not parse `go list -json` stream: {exc}") from exc
        if not isinstance(value, dict):
            raise GoSymbolSourceObservationError("`go list -json` stream contained a non-object")
        values.append(value)
    return values


def _string_list(value: object, *, field: str, package: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise GoSymbolSourceObservationError(
            f"Go package {package!r} field {field} is not a non-empty-string array"
        )
    return tuple(sorted(set(value)))


def _optional_bool(value: object, *, field: str, package: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise GoSymbolSourceObservationError(
            f"Go package {package!r} field {field} is not a boolean"
        )
    return value


def _module_input(value: object, package: str) -> GoSymbolModuleInput | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise GoSymbolSourceObservationError(f"Go package {package!r} Module is not an object")
    path = value.get("Path")
    if not isinstance(path, str) or not path:
        raise GoSymbolSourceObservationError(f"Go package {package!r} Module is missing Path")
    raw_version = value.get("Version")
    if raw_version is not None and (not isinstance(raw_version, str) or not raw_version):
        raise GoSymbolSourceObservationError(
            f"Go package {package!r} Module.Version is not a non-empty string"
        )
    version = raw_version
    effective_path = path
    effective_version = version
    replacement = value.get("Replace")
    if replacement is not None:
        if not isinstance(replacement, dict):
            raise GoSymbolSourceObservationError(f"Go package {package!r} Module.Replace is not an object")
        replacement_path = replacement.get("Path")
        if not isinstance(replacement_path, str) or not replacement_path:
            raise GoSymbolSourceObservationError(
                f"Go package {package!r} replacement is missing Path identity"
            )
        replacement_version = replacement.get("Version")
        if replacement_version is not None and (
            not isinstance(replacement_version, str) or not replacement_version
        ):
            raise GoSymbolSourceObservationError(
                f"Go package {package!r} Module.Replace.Version is not a non-empty string"
            )
        effective_path = replacement_path
        effective_version = replacement_version
    return GoSymbolModuleInput(
        path=path,
        version=version,
        main=_optional_bool(value.get("Main"), field="Module.Main", package=package),
        effective_path=effective_path,
        effective_version=effective_version,
    )


def parse_go_symbol_package_inputs(text: str) -> tuple[GoSymbolPackageInput, ...]:
    packages: list[GoSymbolPackageInput] = []
    seen_import_paths: set[str] = set()
    for record in _decode_json_stream(text):
        import_path = record.get("ImportPath")
        if not isinstance(import_path, str) or not import_path:
            raise GoSymbolSourceObservationError("Go package record is missing ImportPath")
        if import_path in seen_import_paths:
            raise GoSymbolSourceObservationError(
                f"`go list -json` source observation contains duplicate ImportPath {import_path!r}"
            )
        seen_import_paths.add(import_path)
        if _optional_bool(record.get("Incomplete"), field="Incomplete", package=import_path):
            raise GoSymbolSourceObservationError(f"Go package {import_path!r} is incomplete")
        if record.get("Error") is not None:
            raise GoSymbolSourceObservationError(f"Go package {import_path!r} contains an Error record")
        deps_errors = record.get("DepsErrors")
        if deps_errors is not None and not isinstance(deps_errors, list):
            raise GoSymbolSourceObservationError(
                f"Go package {import_path!r} field DepsErrors is not an array"
            )
        if deps_errors:
            raise GoSymbolSourceObservationError(f"Go package {import_path!r} contains dependency errors")
        raw_name = record.get("Name")
        if raw_name is not None and (not isinstance(raw_name, str) or not raw_name):
            raise GoSymbolSourceObservationError(
                f"Go package {import_path!r} field Name is not a non-empty string"
            )
        directory = record.get("Dir")
        if not isinstance(directory, str) or not directory:
            raise GoSymbolSourceObservationError(f"Go package {import_path!r} is missing Dir")
        directory_path = Path(directory)
        if not directory_path.is_absolute():
            raise GoSymbolSourceObservationError(
                f"Go package {import_path!r} field Dir is not an absolute path"
            )

        compiled_go_files = _string_list(
            record.get("CompiledGoFiles"),
            field="CompiledGoFiles",
            package=import_path,
        )
        source_files = tuple(
            (field, _string_list(record.get(field), field=field, package=import_path))
            for field in SOURCE_FILE_FIELDS
            if record.get(field) is not None
        )
        ignored_files = tuple(
            (field, _string_list(record.get(field), field=field, package=import_path))
            for field in IGNORED_FILE_FIELDS
            if record.get(field) is not None
        )
        packages.append(GoSymbolPackageInput(
            import_path=import_path,
            name=raw_name,
            standard=_optional_bool(record.get("Standard"), field="Standard", package=import_path),
            dep_only=_optional_bool(record.get("DepOnly"), field="DepOnly", package=import_path),
            directory=str(directory_path.resolve()),
            module=_module_input(record.get("Module"), import_path),
            compiled_go_files=compiled_go_files,
            source_files=source_files,
            ignored_files=ignored_files,
            imports=_string_list(record.get("Imports"), field="Imports", package=import_path),
        ))
    normalized = tuple(sorted(packages, key=lambda package: package.import_path))
    if not normalized:
        raise GoSymbolSourceObservationError(
            "`go list -json` source observation contains no package records"
        )
    if not any(not package.dep_only for package in normalized):
        raise GoSymbolSourceObservationError(
            "`go list -json` source observation contains no root package selected by ./..."
        )
    return normalized


def execute_go_symbol_source_observation(
    plan: GoSymbolSourceObservationPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> GoSymbolSourceObservationExecution:
    executable = which(plan.env_argv[0])
    if executable is None:
        return GoSymbolSourceObservationExecution(
            plan, 127, None, "", "Go executable is not available",
        )
    environment = dict(os.environ)
    environment.update(plan.environment)

    def invoke(argv_template: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        argv = [executable, *argv_template[1:]]
        return run(
            argv,
            cwd=plan.cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    try:
        env_result = invoke(plan.env_argv)
    except OSError as exc:
        return GoSymbolSourceObservationExecution(plan, 127, None, "", str(exc))
    if env_result.returncode != 0:
        detail = (env_result.stderr or env_result.stdout or "").strip()
        return GoSymbolSourceObservationExecution(
            plan, env_result.returncode, None, detail,
            f"`go env -json` failed with exit code {env_result.returncode}",
        )
    try:
        build_environment = parse_go_symbol_build_environment(env_result.stdout or "")
        validate_go_symbol_loader_profile_version(build_environment)
    except GoSymbolSourceObservationError as exc:
        return GoSymbolSourceObservationExecution(plan, 1, None, "", str(exc))

    try:
        package_result = invoke(plan.packages_argv)
    except OSError as exc:
        return GoSymbolSourceObservationExecution(plan, 127, None, "", str(exc))
    if package_result.returncode != 0:
        detail = (package_result.stderr or package_result.stdout or "").strip()
        return GoSymbolSourceObservationExecution(
            plan, package_result.returncode, None, detail,
            f"normalized `go list` source observation failed with exit code {package_result.returncode}",
        )
    try:
        packages = parse_go_symbol_package_inputs(package_result.stdout or "")
    except GoSymbolSourceObservationError as exc:
        return GoSymbolSourceObservationExecution(
            plan, 1, None, (package_result.stderr or "").strip(), str(exc)
        )

    return GoSymbolSourceObservationExecution(
        plan=plan,
        returncode=0,
        observation=GoSymbolSourceObservation(build_environment, packages),
        stderr=(package_result.stderr or env_result.stderr or "").strip(),
        error=None,
    )
