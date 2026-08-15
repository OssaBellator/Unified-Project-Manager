from __future__ import annotations

import re
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ResolvedPackage, ToolchainRequirement
from .base import Adapter

_DIRECTIVE = re.compile(r"^\s*(module|go|toolchain)\s+(.+?)\s*$")
_REQUIRE = re.compile(r"^\s*([^\s]+)\s+(v[^\s]+)(?:\s+//\s*indirect)?\s*$")
_SUM = re.compile(r"^([^\s]+)\s+(v[^\s/]+)(?:/go\.mod)?\s+h1:[A-Za-z0-9+/=]+\s*$")


class GoAdapter(Adapter):
    ecosystem = "go"

    def detect(self, directory: Path) -> bool:
        return (directory / "go.mod").is_file()

    def inspect(self, directory: Path) -> Component:
        go_mod = directory / "go.mod"
        go_sum = directory / "go.sum"
        metadata: dict[str, object] = {}
        dependencies: list[Dependency] = []
        resolved: dict[tuple[str, str], ResolvedPackage] = {}
        toolchains: list[ToolchainRequirement] = []

        try:
            lines = go_mod.read_text(encoding="utf-8").splitlines()
            in_require = False
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                if line == "require (":
                    in_require = True
                    continue
                if in_require and line == ")":
                    in_require = False
                    continue

                directive = _DIRECTIVE.match(raw)
                if directive:
                    kind, value = directive.groups()
                    value = value.strip()
                    if kind == "module":
                        metadata["name"] = value
                    elif kind == "go":
                        metadata["go_version"] = value
                        toolchains = [ToolchainRequirement("go", value)]
                    elif kind == "toolchain":
                        metadata["go_toolchain"] = value
                    continue

                candidate = line
                if not in_require and candidate.startswith("require "):
                    candidate = candidate.removeprefix("require ").strip()
                elif not in_require:
                    continue
                match = _REQUIRE.match(candidate)
                if match:
                    name, version = match.groups()
                    scope = "indirect" if "// indirect" in raw else "runtime"
                    dependencies.append(Dependency(name, version, scope))
        except (OSError, UnicodeDecodeError) as exc:
            metadata["parse_error"] = str(exc)

        if not toolchains:
            toolchains.append(ToolchainRequirement("go"))

        if go_sum.is_file():
            try:
                for raw in go_sum.read_text(encoding="utf-8").splitlines():
                    match = _SUM.match(raw.strip())
                    if not match:
                        continue
                    name, version = match.groups()
                    resolved[(name, version)] = ResolvedPackage(name=name, version=version, source="go.sum", location="go.sum")
            except (OSError, UnicodeDecodeError) as exc:
                metadata.setdefault("lockfile_parse_errors", []).append(f"go.sum: {exc}")

        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager="go",
            manifests=["go.mod"],
            lockfiles=["go.sum"] if go_sum.is_file() else [],
            toolchains=toolchains,
            dependencies=sorted(dependencies, key=lambda item: (item.scope, item.name)),
            resolved_packages=sorted(resolved.values(), key=lambda item: (item.name, item.version)),
            metadata=metadata,
        )
