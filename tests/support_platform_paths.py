from __future__ import annotations

import tempfile
from pathlib import Path


def platform_absolute_fixture(*parts: str) -> str:
    """Return a deterministic platform-absolute synthetic path without touching disk."""

    return str((Path(tempfile.gettempdir()) / "upm-test-fixtures" / Path(*parts)).resolve())
