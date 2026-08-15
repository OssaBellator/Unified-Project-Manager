from __future__ import annotations

from typing import Any


def render_python_lock_query(payload: dict[str, Any], *, indent: str = "  ") -> list[str]:
    """Render one command-neutral Poetry/PDM query without losing uncertainty.

    The JSON query object remains authoritative; this helper keeps project why,
    project impact, and fleet impact text output aligned with the same resolved,
    possible, ambiguity, and truncation states.
    """
    lines: list[str] = []

    for package in payload.get("packages", []):
        if not isinstance(package, dict):
            continue
        certainty = "unconditional" if package.get("unconditional") else "conditional"
        lines.append(f"{indent}{package.get('name')}@{package.get('version')} [{certainty}]")
        for path in package.get("paths", []):
            if not isinstance(path, dict):
                continue
            nodes = [str(node) for node in path.get("nodes", [])]
            lines.append(f"{indent}  path: " + " -> ".join(nodes))
            markers = [str(marker) for marker in path.get("markers", [])]
            if markers:
                lines.append(f"{indent}  markers: " + " && ".join(markers))
            if path.get("optional_edges"):
                lines.append(f"{indent}  optional edges: {path['optional_edges']}")
        if package.get("paths_truncated"):
            lines.append(f"{indent}  ! additional paths were truncated")

    for package in payload.get("possible_packages", []):
        if not isinstance(package, dict):
            continue
        lines.append(
            f"{indent}{package.get('name')}@{package.get('version')} "
            "[possible via ambiguous lock reference]"
        )
        for path in package.get("paths", []):
            if not isinstance(path, dict):
                continue
            nodes = [str(node) for node in path.get("nodes", [])]
            lines.append(f"{indent}  possible path: " + " -> ".join(nodes))
            markers = [str(marker) for marker in path.get("markers", [])]
            if markers:
                lines.append(f"{indent}  markers: " + " && ".join(markers))
            if path.get("optional_edges"):
                lines.append(f"{indent}  optional edges: {path['optional_edges']}")
        if package.get("paths_truncated"):
            lines.append(f"{indent}  ! additional possible paths were truncated")

    for ambiguity in payload.get("ambiguities", []):
        if not isinstance(ambiguity, dict):
            continue
        candidates = ", ".join(str(value) for value in ambiguity.get("candidate_ids", []))
        lines.append(
            f"{indent}? {ambiguity.get('source')} -> {ambiguity.get('dependency_name')} "
            f"[ambiguous candidates: {candidates}]"
        )
        for path in ambiguity.get("paths", []):
            if not isinstance(path, dict):
                continue
            nodes = [str(node) for node in path.get("nodes", [])]
            lines.append(f"{indent}  ambiguity path: " + " -> ".join(nodes))
            markers = [str(marker) for marker in path.get("markers", [])]
            if markers:
                lines.append(f"{indent}  markers: " + " && ".join(markers))
            if path.get("optional_edges"):
                lines.append(f"{indent}  optional edges: {path['optional_edges']}")
        if ambiguity.get("paths_truncated"):
            lines.append(f"{indent}  ! additional ambiguity paths were truncated")

    if payload.get("search_truncated"):
        lines.append(f"{indent}! relationship search state budget was reached; paths are incomplete")
    return lines
