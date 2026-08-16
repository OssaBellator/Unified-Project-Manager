from __future__ import annotations

import os
from collections.abc import Mapping


class GoSymbolToolchainPathError(ValueError):
    """Raised when the preflight-resolved Go executable cannot be bound to PATH."""


_ENVIRONMENT_KEYS_CASE_INSENSITIVE = os.name == "nt"


def environment_with_preflight_go_path(
    environment: Mapping[str, str],
    go_executable: str,
) -> dict[str, str]:
    """Return an environment whose PATH resolves `go` from the preflight directory first."""
    if not os.path.isabs(go_executable):
        raise GoSymbolToolchainPathError(
            "preflight-resolved Go executable path is not absolute"
        )
    directory = os.path.dirname(go_executable)
    if not directory:
        raise GoSymbolToolchainPathError(
            "preflight-resolved Go executable has no directory component"
        )

    result = dict(environment)
    existing = result.get("PATH", "")
    if _ENVIRONMENT_KEYS_CASE_INSENSITIVE:
        path_keys = [key for key in result if key.upper() == "PATH"]
        if "PATH" not in result and path_keys:
            existing = result[path_keys[0]]
        for key in path_keys:
            if key != "PATH":
                result.pop(key, None)
    result["PATH"] = directory if not existing else directory + os.pathsep + existing
    return result
