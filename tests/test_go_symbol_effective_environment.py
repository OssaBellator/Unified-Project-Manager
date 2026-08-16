from __future__ import annotations

import unittest

from unified_project_manager.go_symbol_effective_environment import (
    GO_SYMBOL_GOENV_DISABLED,
    environment_with_persisted_go_config_disabled,
    go_symbol_effective_goflags_blocker,
)
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolBuildEnvironment,
    GoSymbolSourceObservation,
)


class GoSymbolEffectiveEnvironmentTests(unittest.TestCase):
    def _observation(self, *values: tuple[str, str]) -> GoSymbolSourceObservation:
        return GoSymbolSourceObservation(GoSymbolBuildEnvironment(tuple(values)), ())

    def test_disables_persisted_go_config_without_erasing_process_goflags(self) -> None:
        original = {"GOFLAGS": "-tags=ambient", "OTHER": "kept"}
        environment = environment_with_persisted_go_config_disabled(original)

        self.assertEqual(environment["GOENV"], GO_SYMBOL_GOENV_DISABLED)
        self.assertEqual(environment["GOFLAGS"], "-tags=ambient")
        self.assertEqual(environment["OTHER"], "kept")
        self.assertNotIn("GOENV", original)

    def test_preserves_existing_goenv_key_casing_without_duplicates(self) -> None:
        environment = environment_with_persisted_go_config_disabled(
            {"GoEnv": "/tmp/persisted", "GOENV": "/tmp/duplicate"}
        )
        goenv_keys = [key for key in environment if key.upper() == "GOENV"]
        self.assertEqual(goenv_keys, ["GoEnv"])
        self.assertEqual(environment["GoEnv"], GO_SYMBOL_GOENV_DISABLED)

    def test_explicit_empty_goflags_allows_real_alignment_gate(self) -> None:
        self.assertIsNone(
            go_symbol_effective_goflags_blocker(self._observation(("GOFLAGS", "")))
        )

    def test_nonempty_effective_goflags_blocks_real_alignment_gate(self) -> None:
        reason = go_symbol_effective_goflags_blocker(
            self._observation(("GOFLAGS", "-tags=ambient"))
        )
        self.assertIsNotNone(reason)
        self.assertIn("-tags=ambient", reason or "")
        self.assertIn("not empty", reason or "")

    def test_missing_effective_goflags_fails_closed(self) -> None:
        reason = go_symbol_effective_goflags_blocker(self._observation(("GOOS", "linux")))
        self.assertIsNotNone(reason)
        self.assertIn("missing effective GOFLAGS", reason or "")


if __name__ == "__main__":
    unittest.main()
