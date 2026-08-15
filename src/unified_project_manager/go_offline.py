from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import Any


def offline_go_run(
    argv: list[str],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a Go command with module proxy lookup disabled.

    Existing environment overrides (for example GOWORK/GOFLAGS) are preserved,
    while GOPROXY=off makes the control-plane's default native graph queries
    local/cache-only. Commands fail explicitly when required module data is not
    already available locally instead of silently contacting a module proxy.
    """
    environment = dict(os.environ)
    supplied = kwargs.pop("env", None)
    if isinstance(supplied, dict):
        environment.update({str(key): str(value) for key, value in supplied.items()})
    environment["GOPROXY"] = "off"
    return run(argv, env=environment, **kwargs)
