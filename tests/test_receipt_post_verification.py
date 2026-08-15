from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.receipt_execution import execute_plans_with_receipt


@dataclass(frozen=True)
class FakePlan:
    component: str
    manager: str
    cwd: Path
    argv: tuple[str, ...]


@dataclass
class FakeResult:
    returncode: int


class ReceiptPostVerificationTests(unittest.TestCase):
    def test_verify_after_runs_on_rediscovered_graph_and_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(
                '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
            )
            graph = discover(root)
            plan = FakePlan(".:node", "npm", root, ("npm", "install"))
            seen = []

            def verify_after(after_graph):
                seen.append(after_graph)
                return {
                    "health_score": 100,
                    "summary": {"errors": 0, "warnings": 0, "infos": 0},
                }

            execution = execute_plans_with_receipt(
                graph,
                "install",
                [plan],
                lambda _plan: FakeResult(0),
                verify_after=verify_after,
            )

            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].root, root)
            self.assertEqual(execution.receipt.verification["health_score"], 100)
            self.assertEqual(
                execution.receipt.to_dict()["verification"]["summary"]["errors"],
                0,
            )


if __name__ == "__main__":
    unittest.main()
