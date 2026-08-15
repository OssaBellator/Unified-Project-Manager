from __future__ import annotations

import re
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ToolchainRequirement
from .base import Adapter

_DIRECTIVE = re.compile(r"^\s*(module|go|toolchain)\s+(.+?)\s*$")
_REQUIRE = re.compile(r"^\s*([^\s]+)\s+(v[^\s]+)(?:\s+//\s*indirect)?\s*$")


class GoAdapter(Adapter):
    ecosystem = "go"

    def detect(self, directory: Path) -> bool:
        return (directory / "go.mod").is_file()

    def inspect(self, directory: Path) -> Component:
        go_mod = directory / "go.mod"
        go_sum = directory / "go.sum"
        metadata: dict[str, object] = {}
        dependencies: list[Dependency] = []
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
                lines = [line for line in go_sum.read_text(encoding="utf-8").splitlines() if line.strip()]
                metadata["checksum_entries"] = len(lines)
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
            resolved_packages=[],
            metadata=metadata,
        )
