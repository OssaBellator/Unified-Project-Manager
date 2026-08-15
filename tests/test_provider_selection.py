from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.cargo_graph import plan_cargo_graphs
from unified_project_manager.discovery import discover


class ProviderSelectionTests(unittest.TestCase):
    def test_cargo_member_selector_promotes_to_workspace_root_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "member"
            member.mkdir()
            (root / "Cargo.toml").write_text('[workspace]\nmembers=["member"]\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
            (member / "Cargo.toml").write_text('[package]\nname="member"\nversion="0.1.0"\n', encoding="utf-8")

            plans = plan_cargo_graphs(discover(root), selector="member")

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:rust")
            self.assertEqual(plans[0].cwd, root)


if __name__ == "__main__":
    unittest.main()
