from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from unified_project_manager.models import Component


class Adapter(ABC):
    """Translate one ecosystem's native project files into the normalized model."""

    ecosystem: str

    @abstractmethod
    def detect(self, directory: Path) -> bool:
        """Return True when this directory is a project root for the ecosystem."""

    @abstractmethod
    def inspect(self, directory: Path) -> Component:
        """Read native manifests/lockfiles and return a normalized component."""
