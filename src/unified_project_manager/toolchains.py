from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .models import Finding, ProjectGraph

TOOLCHAIN_EXECUTABLES = {"go": "go", "node": "node", "python": "python", "rust": "rustc"}
_VERSION_COMMANDS = {
    "go": ("go", "version"),
    "node": ("node", "--version"),
    "python": ("python", "--version"),
    "rust": ("rustc", "--version"),
}
_VERSION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+){0,3})(?!\d)")


@dataclass(frozen=True, order=True)
class NumericVersion:
    parts: tuple[int, ...]

    @classmethod
    def parse(cls, value: str) -> "NumericVersion | None":
        match = _VERSION_RE.search(value.strip())
        if not match:
            return None
        return cls(tuple(int(part) for part in match.group(1).split(".")))

    def padded(self, length: int = 4) -> tuple[int, ...]:
        return self.parts + (0,) * max(0, length - len(self.parts))

    def compare(self, other: "NumericVersion") -> int:
        length = max(len(self.parts), len(other.parts), 3)
        left = self.padded(length)
        right = other.padded(length)
        return (left > right) - (left < right)

    def __str__(self) -> str:
        return ".".join(str(part) for part in self.parts)


def _cmp(installed: NumericVersion, operator: str, expected: NumericVersion) -> bool:
    comparison = installed.compare(expected)
    return {
        "==": comparison == 0,
        "=": comparison == 0,
        "!=": comparison != 0,
        ">": comparison > 0,
        ">=": comparison >= 0,
        "<": comparison < 0,
        "<=": comparison <= 0,
    }[operator]


def _python_clause(installed: NumericVersion, clause: str) -> bool | None:
    clause = clause.strip()
    if not clause or clause == "*":
        return True
    match = re.fullmatch(r"(===|==|!=|~=|>=|<=|>|<)\s*([0-9]+(?:\.[0-9]+)*(?:\.\*)?)", clause)
    if not match:
        return None
    operator, raw = match.groups()
    if operator == "===":
        operator = "=="
    if raw.endswith(".*"):
        if operator not in {"==", "!="}:
            return None
        prefix = tuple(int(part) for part in raw[:-2].split("."))
        matches = installed.parts[: len(prefix)] == prefix
        return matches if operator == "==" else not matches
    expected = NumericVersion.parse(raw)
    if expected is None:
        return None
    if operator == "~=":
        if installed.compare(expected) < 0:
            return False
        prefix_length = max(1, len(expected.parts) - 1)
        return installed.parts[:prefix_length] == expected.parts[:prefix_length]
    return _cmp(installed, operator, expected)


def satisfies_python(installed: NumericVersion, requirement: str) -> bool | None:
    clauses = [part.strip() for part in requirement.split(",") if part.strip()]
    if not clauses:
        return True
    unknown = False
    for clause in clauses:
        result = _python_clause(installed, clause)
        if result is False:
            return False
        if result is None:
            unknown = True
    return None if unknown else True


def _node_atom(installed: NumericVersion, atom: str) -> bool | None:
    atom = atom.strip()
    if not atom or atom in {"*", "x", "X"}:
        return True

    if atom.startswith("^"):
        expected = NumericVersion.parse(atom[1:])
        if expected is None:
            return None
        if installed.compare(expected) < 0:
            return False
        padded = expected.padded(3)
        if padded[0] > 0:
            upper = NumericVersion((padded[0] + 1, 0, 0))
        elif padded[1] > 0:
            upper = NumericVersion((0, padded[1] + 1, 0))
        else:
            upper = NumericVersion((0, 0, padded[2] + 1))
        return installed.compare(upper) < 0

    if atom.startswith("~"):
        expected = NumericVersion.parse(atom[1:].strip())
        if expected is None:
            return None
        if installed.compare(expected) < 0:
            return False
        if len(expected.parts) <= 1:
            upper = NumericVersion((expected.parts[0] + 1, 0, 0))
        else:
            upper = NumericVersion((expected.parts[0], expected.parts[1] + 1, 0))
        return installed.compare(upper) < 0

    match = re.fullmatch(r"(>=|<=|>|<|=)?\s*([0-9]+(?:\.[0-9]+){0,3}|[0-9]+(?:\.[0-9]+)*\.(?:x|X|\*))", atom)
    if not match:
        return None
    operator = match.group(1)
    raw = match.group(2)
    if raw.endswith((".x", ".X", ".*")):
        if operator not in {None, "="}:
            return None
        prefix = tuple(int(part) for part in raw[:-2].split("."))
        return installed.parts[: len(prefix)] == prefix

    expected = NumericVersion.parse(raw)
    if expected is None:
        return None
    if operator:
        return _cmp(installed, operator, expected)
    if len(expected.parts) >= 3:
        return _cmp(installed, "==", expected)
    return installed.parts[: len(expected.parts)] == expected.parts


def _node_set(installed: NumericVersion, expression: str) -> bool | None:
    expression = expression.strip()
    hyphen = re.fullmatch(r"([0-9]+(?:\.[0-9]+){0,2})\s+-\s+([0-9]+(?:\.[0-9]+){0,2})", expression)
    if hyphen:
        lower = NumericVersion.parse(hyphen.group(1))
        upper = NumericVersion.parse(hyphen.group(2))
        if lower is None or upper is None:
            return None
        return installed.compare(lower) >= 0 and installed.compare(upper) <= 0

    atoms = expression.split()
    if not atoms:
        return True
    unknown = False
    for atom in atoms:
        result = _node_atom(installed, atom)
        if result is False:
            return False
        if result is None:
            unknown = True
    return None if unknown else True


def satisfies_node(installed: NumericVersion, requirement: str) -> bool | None:
    alternatives = [part.strip() for part in requirement.split("||")]
    saw_unknown = False
    for alternative in alternatives:
        result = _node_set(installed, alternative)
        if result is True:
            return True
        if result is None:
            saw_unknown = True
    return None if saw_unknown else False


def satisfies_minimum(installed: NumericVersion, requirement: str) -> bool | None:
    if not re.fullmatch(r"\s*[0-9]+(?:\.[0-9]+){0,2}\s*", requirement):
        return None
    expected = NumericVersion.parse(requirement)
    return None if expected is None else installed.compare(expected) >= 0


def satisfies_rust(installed: NumericVersion, requirement: str) -> bool | None:
    return satisfies_minimum(installed, requirement)


def satisfies_go(installed: NumericVersion, requirement: str) -> bool | None:
    return satisfies_minimum(installed, requirement)


def satisfies(name: str, installed: NumericVersion, requirement: str) -> bool | None:
    if not requirement or requirement.strip() == "*":
        return True
    if name == "node":
        return satisfies_node(installed, requirement)
    if name == "python":
        return satisfies_python(installed, requirement)
    if name == "rust":
        return satisfies_rust(installed, requirement)
    if name == "go":
        return satisfies_go(installed, requirement)
    return None


def read_toolchain_version(
    name: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[NumericVersion | None, str | None]:
    command = _VERSION_COMMANDS.get(name, (name, "--version"))
    try:
        completed = run(list(command), text=True, capture_output=True, check=False)
    except OSError as exc:
        return None, str(exc)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        return None, output or f"version command exited with {completed.returncode}"
    version = NumericVersion.parse(output)
    if version is None:
        return None, output or "version command produced no parseable version"
    return version, None


def toolchain_findings(
    graph: ProjectGraph,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Finding]:
    findings: list[Finding] = []
    versions: dict[str, tuple[NumericVersion | None, str | None]] = {}

    for component in graph.components:
        key = component.key(graph.root)
        for requirement in component.toolchains:
            executable = TOOLCHAIN_EXECUTABLES.get(requirement.name, requirement.name)
            if which(executable) is None:
                rendered = f" ({requirement.requirement})" if requirement.requirement else ""
                findings.append(Finding(
                    "toolchain.unavailable",
                    "warning",
                    f"Toolchain '{requirement.name}'{rendered} is not available on PATH.",
                    key,
                ))
                continue
            if not requirement.requirement:
                continue
            if executable not in versions:
                versions[executable] = read_toolchain_version(requirement.name, run=run)
            installed, error = versions[executable]
            if installed is None:
                findings.append(Finding(
                    "toolchain.version-unreadable",
                    "warning",
                    f"Could not determine the installed {requirement.name} version: {error}.",
                    key,
                ))
                continue
            compatible = satisfies(requirement.name, installed, requirement.requirement)
            if compatible is False:
                findings.append(Finding(
                    "toolchain.version-mismatch",
                    "warning",
                    f"Installed {requirement.name} {installed} does not satisfy {requirement.requirement!r}.",
                    key,
                    "Activate a compatible toolchain before installing, building, or testing this component.",
                ))
            elif compatible is None:
                findings.append(Finding(
                    "toolchain.requirement-unverified",
                    "info",
                    f"Installed {requirement.name} is {installed}, but UPM cannot safely evaluate requirement {requirement.requirement!r} yet.",
                    key,
                    "Use the native toolchain/package manager to verify this requirement.",
                ))
    return findings
