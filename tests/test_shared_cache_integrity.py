from __future__ import annotations

import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.shared_cache_integrity import (
    SharedCacheResult,
    execute_shared_cache_plan,
    plan_shared_cache_checks,
    plan_shared_cache_maintenance,
)


class SharedCacheIntegrityTests(unittest.TestCase):
    def test_pnpm_status_is_non_mutating_and_uses_exact_resolved_binary(self) -> None:
        plan = plan_shared_cache_checks(("pnpm",))[0][0]
        self.assertFalse(plan.mutates)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        result = execute_shared_cache_plan(plan, run=run, which=lambda _name: "/tools/pnpm")
        self.assertTrue(result.succeeded)
        self.assertEqual(calls[0], ["/tools/pnpm", "store", "status"])

    def test_pnpm_modified_store_failure_is_preserved(self) -> None:
        plan = plan_shared_cache_checks(("pnpm",))[0][0]

        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, "", "modified package\n")

        result = execute_shared_cache_plan(plan, run=run, which=lambda _name: "/tools/pnpm")
        self.assertFalse(result.succeeded)
        self.assertIn("modified", result.stderr)

    def test_npm_verification_is_classified_as_mutating_maintenance(self) -> None:
        plan = plan_shared_cache_maintenance(("npm",))[0][0]
        self.assertTrue(plan.mutates)
        self.assertEqual(plan.argv, ("npm", "cache", "verify"))
        self.assertIn("garbage-collects", plan.effect)

    def test_cache_check_cli_executes_non_mutating_pnpm_status(self) -> None:
        plan = plan_shared_cache_checks(("pnpm",))[0][0]
        result = SharedCacheResult(plan, 0, "store is valid\n", "")
        output = io.StringIO()
        with patch("unified_project_manager.cache_entrypoint.execute_shared_cache_plan", return_value=result), redirect_stdout(output):
            code = main(["cache", "check", "--json"])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["scope"], "shared-cache-integrity")
        self.assertFalse(data["mutates"])
        self.assertTrue(data["results"][0]["succeeded"])

    def test_npm_cache_verify_is_preview_first(self) -> None:
        output = io.StringIO()
        with patch("unified_project_manager.cache_entrypoint.execute_shared_cache_plan") as execute, redirect_stdout(output):
            code = main(["cache", "verify", "--json"])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(data["executed"])
        self.assertTrue(data["plans"][0]["mutates"])
        self.assertEqual(data["plans"][0]["argv"], ["npm", "cache", "verify"])
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
