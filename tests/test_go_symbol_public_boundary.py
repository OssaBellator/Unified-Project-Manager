from __future__ import annotations

import unittest

from unified_project_manager.provider_registry import PROVIDERS


class GoSymbolPublicBoundaryTests(unittest.TestCase):
    def test_govulncheck_is_not_a_public_relationship_provider(self) -> None:
        names = {provider.provider for provider in PROVIDERS}
        self.assertEqual(len(PROVIDERS), 8)
        self.assertNotIn("govulncheck", names)
        self.assertNotIn("go-symbol-reachability", names)
        self.assertEqual(
            names,
            {
                "go-modules",
                "npm-lock-tree",
                "pnpm-lock-tree",
                "yarn-berry-resolution-graph",
                "cargo-metadata",
                "uv-lock",
                "poetry-lock",
                "pdm-lock",
            },
        )


if __name__ == "__main__":
    unittest.main()
