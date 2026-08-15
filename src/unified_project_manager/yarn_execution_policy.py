from __future__ import annotations

import os
from collections.abc import Mapping


def yarn_base_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the environment UPM supplies to Yarn Berry provider commands.

    Hardened mode is intentionally not set or removed here. If the caller's
    environment already declares it, that ambient choice is preserved.
    """

    env = dict(os.environ if base is None else base)
    env.update({
        "YARN_ENABLE_NETWORK": "0",
        "YARN_ENABLE_TELEMETRY": "0",
        "YARN_ENABLE_IMMUTABLE_CACHE": "1",
        "YARN_ENABLE_COLORS": "0",
    })
    return env


def yarn_execution_guards() -> dict[str, str]:
    """Return the public preview description of enforced Yarn execution policy."""

    return {
        "network": "disabled",
        "install_state": "temporary",
        "cache": "immutable",
        "hardened_mode": "unchanged",
        "telemetry": "disabled",
    }
