from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from unified_project_manager.yarn_execution_policy import (
    yarn_base_environment,
    yarn_execution_guards,
)


class YarnExecutionPolicyTests(unittest.TestCase):
    def test_base_environment_enforces_safety_controls_without_injecting_hardened_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = yarn_base_environment()

        self.assertEqual(env["YARN_ENABLE_NETWORK"], "0")
        self.assertEqual(env["YARN_ENABLE_TELEMETRY"], "0")
        self.assertEqual(env["YARN_ENABLE_IMMUTABLE_CACHE"], "1")
        self.assertEqual(env["YARN_ENABLE_COLORS"], "0")
        self.assertNotIn("YARN_ENABLE_HARDENED_MODE", env)

    def test_ambient_hardened_mode_choice_is_preserved(self) -> None:
        with patch.dict(os.environ, {"YARN_ENABLE_HARDENED_MODE": "1"}, clear=True):
            env = yarn_base_environment()

        self.assertEqual(env["YARN_ENABLE_HARDENED_MODE"], "1")

    def test_preview_guards_describe_hardened_mode_as_unchanged(self) -> None:
        guards = yarn_execution_guards()

        self.assertEqual(guards["network"], "disabled")
        self.assertEqual(guards["install_state"], "temporary")
        self.assertEqual(guards["cache"], "immutable")
        self.assertEqual(guards["telemetry"], "disabled")
        self.assertEqual(guards["hardened_mode"], "unchanged")


if __name__ == "__main__":
    unittest.main()
