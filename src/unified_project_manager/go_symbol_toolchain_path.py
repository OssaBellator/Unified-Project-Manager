from __future__ import annotations

import os
from collections.abc import Mapping


class GoSymbolToolchainPathError(ValueError):
    """Raised when the preflight-resolved Go executable cannot be bound to PATH."""


def environment_with_preflight_go_path(
    environment: Mapping[str, str],
    go_executable: str,
) -> dict[str, str]:
    """Return an environment whose PATH resolves `go` from the preflight directory first."""
    directory = os.path.dirname(go_executable)
    if not directory:
        raise GoSymbolToolchainPathError(
            "preflight-resolved Go executable has no directory component"
        )

    result = dict(environment)
    path_keys = [key for key in result if key.upper() == "PATH"]
    path_key = path_keys[0] if path_keys else "PATH"
    existing = result.get(path_key, "")
    for duplicate in path_keys[1:]:
        result.pop(duplicate, None)
    result[path_key] = directory if not existing else directory + os.pathsep + existing
    return result
