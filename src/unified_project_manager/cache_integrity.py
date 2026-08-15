from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


@dataclass(frozen=True)
class CacheVerificationSkip:
    component: str
    ecosystem: str
    manager: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CacheVerificationResult:
    component: str
    ecosystem: str
    manager: str
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": self.ecosystem,
            "manager": self.manager,
            "argv": list(self.argv),
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def plan_cache_verification(graph: ProjectGraph, selector: str | None = None) -> tuple[list[Component], list[CacheVerificationSkip]]:
    components = list(graph.components)
    if selector is not None:
        components = [
            component for component in components
            if selector in {
                component.key(graph.root),
                component.relative_path(graph.root),
                component.ecosystem,
                component.metadata.get("name"),
            }
        ]
        if not components:
            raise ValueError(f"Unknown component '{selector}'.")
        if len(components) > 1:
            choices = ", ".join(component.key(graph.root) for component in components)
            raise ValueError(f"Component selector '{selector}' is ambiguous: {choices}")

    supported: list[Component] = []
    skips: list[CacheVerificationSkip] = []
    for component in components:
        key = component.key(graph.root)
        if component.ecosystem == "go" and component.manager == "go" and "go.mod" in component.manifests:
            supported.append(component)
        else:
            skips.append(CacheVerificationSkip(
                key,
                component.ecosystem,
                component.manager,
                "authoritative package-cache content verification is not configured for this ecosystem yet",
            ))
    return supported, skips


def verify_go_module_cache(
    component: Component,
    root: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> CacheVerificationResult:
    component_key = component.key(root)
    executable = which("go")
    public_argv = ("go", "mod", "verify", "--isolated-modfile")
    if executable is None:
        return CacheVerificationResult(component_key, "go", "go", public_argv, 127, stderr="Executable 'go' is not available on PATH.")

    source_mod = component.path / "go.mod"
    source_sum = component.path / "go.sum"
    if not source_mod.is_file():
        return CacheVerificationResult(component_key, "go", "go", public_argv, 2, stderr="go.mod is missing.")

    fd, temp_name = tempfile.mkstemp(prefix=".upm-verify-", suffix=".mod", dir=component.path)
    os.close(fd)
    temp_mod = Path(temp_name)
    temp_sum = temp_mod.with_suffix(".sum")
    try:
        shutil.copyfile(source_mod, temp_mod)
        if source_sum.is_file():
            shutil.copyfile(source_sum, temp_sum)
        argv = [executable, "mod", "verify", f"-modfile={temp_mod}"]
        env = dict(os.environ)
        env["GOWORK"] = "off"
        try:
            completed = run(argv, cwd=component.path, text=True, capture_output=True, check=False, env=env)
        except OSError as exc:
            return CacheVerificationResult(component_key, "go", "go", public_argv, 127, stderr=str(exc))
        return CacheVerificationResult(
            component_key,
            "go",
            "go",
            public_argv,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )
    finally:
        for temporary in (temp_sum, temp_mod):
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
