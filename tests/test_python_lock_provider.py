from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph, ResolvedPackage
from unified_project_manager.python_lock_provider import (
    PYTHON_LOCK_SCOPE,
    python_lock_owned_component_keys,
    python_lock_provider_name,
    suppress_python_lock_static_inventory,
)


@dataclass(frozen=True)
class _Plan:
    component: str
    manager: str


class PythonLockProviderBoundaryTests(unittest.TestCase):
    def test_provider_names_and_scope_are_explicit_per_manager(self) -> None:
        self.assertEqual(python_lock_provider_name("poetry"), "poetry-lock")
        self.assertEqual(python_lock_provider_name(_Plan(".:python", "pdm")), "pdm-lock")
        self.assertEqual(PYTHON_LOCK_SCOPE, "structured-lock-dependency-graph")
        with self.assertRaises(ValueError):
            python_lock_provider_name("pip")

    def test_owned_component_keys_are_plan_based(self) -> None:
        plans = [_Plan(".:python", "poetry"), _Plan("tools:python", "pdm")]
        self.assertEqual(
            python_lock_owned_component_keys(plans),
            {".:python", "tools:python"},
        )

    def test_native_static_suppression_only_clears_structured_provider_owners(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            poetry = Component(
                ecosystem="python",
                path=root,
                manager="poetry",
                lockfiles=["poetry.lock"],
                resolved_packages=[ResolvedPackage("orphan", "9.9.9", location="poetry.lock")],
            )
            other_path = root / "legacy"
            other_path.mkdir()
            legacy = Component(
                ecosystem="python",
                path=other_path,
                manager="pip",
                resolved_packages=[ResolvedPackage("kept", "1.0.0", location="requirements.txt")],
            )
            graph = ProjectGraph(root, [poetry, legacy])

            prepared = suppress_python_lock_static_inventory(
                graph,
                [_Plan(".:python", "poetry")],
            )

            self.assertEqual(graph.components[0].resolved_packages[0].name, "orphan")
            self.assertEqual(prepared.components[0].resolved_packages, [])
            self.assertEqual(prepared.components[1].resolved_packages[0].name, "kept")


if __name__ == "__main__":
    unittest.main()
