from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.yarn_graph import YarnGraphPlan, execute_yarn_graph


class YarnExecutionCompatibilityTests(unittest.TestCase):
    def test_provider_does_not_inject_hardened_mode_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            plan = YarnGraphPlan(".:node", root, root, True)
            calls: list[tuple[list[str], dict]] = []
            state_path: Path | None = None

            def run(argv, **kwargs):
                nonlocal state_path
                calls.append((list(argv), kwargs))
                env = kwargs["env"]
                self.assertNotIn("YARN_ENABLE_HARDENED_MODE", env)
                self.assertEqual(env["YARN_ENABLE_NETWORK"], "0")
                self.assertEqual(env["YARN_ENABLE_TELEMETRY"], "0")
                self.assertEqual(env["YARN_ENABLE_IMMUTABLE_CACHE"], "1")
                if argv[1:] == ["--version"]:
                    return subprocess.CompletedProcess(argv, 0, "2.4.3\n", "")
                state_path = Path(env["YARN_INSTALL_STATE_PATH"])
                self.assertFalse(state_path.is_relative_to(root))
                self.assertTrue(state_path.parent.is_dir())
                return subprocess.CompletedProcess(argv, 0, "", "")

            result = execute_yarn_graph(plan, run=run, which=lambda _name: "/tools/yarn")

            self.assertTrue(result.succeeded)
            self.assertEqual(result.yarn_version, "2.4.3")
            self.assertEqual(calls[0][0], ["/tools/yarn", "--version"])
            self.assertEqual(calls[1][0], [
                "/tools/yarn", "info", "--all", "--recursive", "--virtuals", "--json",
            ])
            assert state_path is not None
            self.assertFalse(state_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
