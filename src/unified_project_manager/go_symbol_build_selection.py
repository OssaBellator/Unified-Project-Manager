from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .go_symbol_reachability import GovulncheckSymbolPlan
from .go_symbol_source_observation import GoSymbolSourceObservationPlan


class GoSymbolBuildSelectionError(ValueError):
    """Raised when planned source-analysis package selection cannot be interpreted safely."""


EXPECTED_BUILD_SELECTION_ENVIRONMENT = (
    ("GOPROXY", "off"),
    ("GOWORK", "off"),
    ("GOSUMDB", "off"),
    ("GOTOOLCHAIN", "local"),
    ("GOENV", "off"),
)


@dataclass(frozen=True)
class GoSymbolBuildSelection:
    patterns: tuple[str, ...]
    tags: tuple[str, ...]
    tests: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoSymbolBuildSelectionAlignment:
    govulncheck: GoSymbolBuildSelection
    source_observation: GoSymbolBuildSelection
    differences: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.differences

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": self.matches,
            "govulncheck": self.govulncheck.to_dict(),
            "source_observation": self.source_observation.to_dict(),
            "differences": list(self.differences),
            "scope": "planned-go-symbol-build-selection-alignment",
            "freshness": "not-established",
            "govulncheck_runtime_equivalence": "not-established",
            "interpretation": (
                "planned package-pattern/build-tag/test-selection plus normalized offline/toolchain "
                "environment-overlay agreement only; a match does not prove identical go/packages "
                "loading, selected syntax, call graph, source freshness, runtime behavior, or exploitability"
            ),
        }


def _split_tags(value: str) -> tuple[str, ...]:
    tags = [item.strip() for item in value.split(",")]
    if any(not item for item in tags):
        raise GoSymbolBuildSelectionError("build tag list contains an empty tag")
    return tuple(sorted(set(tags)))


def _bool_flag_value(text: str, *, flag: str) -> bool:
    value = text.strip().lower()
    if value in {"1", "t", "true", "y", "yes"}:
        return True
    if value in {"0", "f", "false", "n", "no"}:
        return False
    raise GoSymbolBuildSelectionError(f"{flag} has unsupported boolean value {text!r}")


def govulncheck_build_selection(plan: GovulncheckSymbolPlan) -> GoSymbolBuildSelection:
    argv = list(plan.argv)
    if not argv:
        raise GoSymbolBuildSelectionError("govulncheck plan argv is empty")

    patterns: list[str] = []
    tags: tuple[str, ...] = ()
    tests = False
    mode: str | None = None
    scan: str | None = None

    value_flags = {"-C", "-db", "-format", "-mode", "-scan", "-show", "-tags"}
    index = 1
    while index < len(argv):
        item = argv[index]
        if item in value_flags:
            if index + 1 >= len(argv):
                raise GoSymbolBuildSelectionError(f"govulncheck option {item} is missing its value")
            value = argv[index + 1]
            if item == "-tags":
                tags = _split_tags(value)
            elif item == "-mode":
                mode = value
            elif item == "-scan":
                scan = value
            index += 2
            continue
        if item.startswith("-tags="):
            tags = _split_tags(item.split("=", 1)[1])
        elif item.startswith("-mode="):
            mode = item.split("=", 1)[1]
        elif item.startswith("-scan="):
            scan = item.split("=", 1)[1]
        elif item == "-test":
            tests = True
        elif item.startswith("-test="):
            tests = _bool_flag_value(item.split("=", 1)[1], flag="-test")
        elif item.startswith("-"):
            # Other govulncheck switches do not change package selection.
            pass
        else:
            patterns.append(item)
        index += 1

    if mode != "source":
        raise GoSymbolBuildSelectionError(
            f"govulncheck plan is not explicit source mode: {mode!r}"
        )
    if scan != "symbol":
        raise GoSymbolBuildSelectionError(
            f"govulncheck plan is not explicit symbol scan level: {scan!r}"
        )
    if not patterns:
        raise GoSymbolBuildSelectionError("govulncheck source plan has no package patterns")
    return GoSymbolBuildSelection(tuple(patterns), tags, tests)


def source_observation_build_selection(
    plan: GoSymbolSourceObservationPlan,
) -> GoSymbolBuildSelection:
    argv = list(plan.packages_argv)
    if len(argv) < 2 or argv[1] != "list":
        raise GoSymbolBuildSelectionError("source observation is not a `go list` plan")

    patterns: list[str] = []
    tags: tuple[str, ...] = ()
    tests = False
    # go list accepts these with a following value when not expressed as -flag=value.
    value_flags = {
        "-asmflags", "-buildmode", "-compiler", "-gcflags", "-go", "-ldflags",
        "-mod", "-modfile", "-overlay", "-p", "-tags", "-toolexec",
    }
    index = 2
    while index < len(argv):
        item = argv[index]
        if item in value_flags:
            if index + 1 >= len(argv):
                raise GoSymbolBuildSelectionError(f"go list option {item} is missing its value")
            value = argv[index + 1]
            if item == "-tags":
                tags = _split_tags(value)
            index += 2
            continue
        if item.startswith("-tags="):
            tags = _split_tags(item.split("=", 1)[1])
        elif item == "-test":
            tests = True
        elif item.startswith("-test="):
            tests = _bool_flag_value(item.split("=", 1)[1], flag="-test")
        elif item.startswith("-"):
            pass
        else:
            patterns.append(item)
        index += 1

    if not patterns:
        raise GoSymbolBuildSelectionError("source observation go-list plan has no package patterns")
    return GoSymbolBuildSelection(tuple(patterns), tags, tests)


def compare_go_symbol_build_selection(
    govulncheck_plan: GovulncheckSymbolPlan,
    source_observation_plan: GoSymbolSourceObservationPlan,
) -> GoSymbolBuildSelectionAlignment:
    """Compare planned package-selection and normalized environment knobs.

    Current govulncheck source loading uses package patterns, optional build tags,
    and optional test inclusion to configure go/packages. UPM keeps these knobs
    aligned and also requires the two plans to preserve the same expected
    offline/single-toolchain environment overlay before treating the Go-native
    observation as candidate scanner input evidence. This remains plan-level
    agreement only, not runtime equivalence.

    Test-enabled selection deliberately fails closed even if both command lines
    request tests. packages.Config{Tests:true} and `go list -test` expand package
    variants differently enough that UPM requires a real-scanner alignment proof
    before accepting that mode as equivalent candidate input evidence.
    """

    scanner = govulncheck_build_selection(govulncheck_plan)
    observation = source_observation_build_selection(source_observation_plan)
    differences: list[str] = []
    if scanner.patterns != observation.patterns:
        differences.append("package patterns differ")
    if scanner.tags != observation.tags:
        differences.append("build tags differ")
    if scanner.tests != observation.tests:
        differences.append("test inclusion differs")
    elif scanner.tests:
        differences.append("test-enabled selection equivalence is not established")

    for key, expected in EXPECTED_BUILD_SELECTION_ENVIRONMENT:
        scanner_value = govulncheck_plan.environment.get(key)
        observation_value = source_observation_plan.environment.get(key)
        if scanner_value != observation_value:
            differences.append(f"{key} environment differs")
        elif scanner_value != expected:
            differences.append(f"{key} environment is not normalized")

    return GoSymbolBuildSelectionAlignment(scanner, observation, tuple(differences))
