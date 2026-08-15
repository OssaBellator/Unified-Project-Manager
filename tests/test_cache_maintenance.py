from __future__ import annotations

import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from unified_project_manager.cache_maintenance import (
    CacheMaintenanceError,
    execute_cache_maintenance,
    plan_cache_clean,
    plan_cache_prune,
)
from unified_project_manager.entrypoint import main


class CacheMaintenanceTests(unittest.TestCase):
    def test_prune_plans_are_authoritative_and_rebuildable(self) -> None:
        plans = plan_cache_prune(("pnpm", "uv"))
        by_manager = {plan.manager: plan for plan in plans}
        self.assertEqual(by_manager["pnpm"].argv, ("pnpm", "store", "prune"))
        self.assertEqual(by_manager["uv"].argv, ("uv", "cache", "prune"))
        self.assertTrue(by_manager["pnpm"].destructive)
        self.assertTrue(by_manager["uv"].redownload_or_rebuild_possible)

    def test_full_clean_requires_explicit_go_category(self) -> None:
        with self.assertRaisesRegex(CacheMaintenanceError, "requires --category"):
            plan_cache_clean("go")
        self.assertEqual(plan_cache_clean("go", go_category="build").argv, ("go", "clean", "-cache"))
        self.assertEqual(plan_cache_clean("go", go_category="modules").argv, ("go", "clean", "-modcache"))
        self.assertEqual(plan_cache_clean("npm").argv, ("npm", "cache", "clean", "--force"))

    def test_execution_uses_exact_resolved_manager(self) -> None:
        plan = plan_cache_clean("npm")
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "cleared\n", "")

        result = execute_cache_maintenance(plan, run=run, which=lambda _name: "/tools/npm")
        self.assertTrue(result.succeeded)
        self.assertEqual(calls[0][0], ["/tools/npm", "cache", "clean", "--force"])
        self.assertNotIn("shell", calls[0][1])

    def test_prune_cli_is_preview_first_and_not_storage_derived(self) -> None:
        output = io.StringIO()
        with patch("unified_project_manager.cache_maintenance_entrypoint.execute_cache_maintenance") as execute, redirect_stdout(output):
            code = main(["cache", "prune", "--manager", "uv", "--json"])
        execute.assert_not_called()
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(data["executed"])
        self.assertFalse(data["automatic"])
        self.assertFalse(data["derived_from_storage_measurement"])
        self.assertEqual(data["plans"][0]["argv"], ["uv", "cache", "prune"])

    def test_clean_cli_is_preview_first(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["cache", "clean", "--manager", "go", "--category", "modules", "--json"])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(data["executed"])
        self.assertEqual(data["plans"][0]["scope"], "module-cache")
        self.assertEqual(data["plans"][0]["argv"], ["go", "clean", "-modcache"])

    def test_apply_executes_only_the_selected_plan(self) -> None:
        fake_result = execute_cache_maintenance(
            plan_cache_prune(("pnpm",))[0],
            run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "pruned\n", ""),
            which=lambda _name: "/tools/pnpm",
        )
        output = io.StringIO()
        with patch("unified_project_manager.cache_maintenance_entrypoint.execute_cache_maintenance", return_value=fake_result) as execute, redirect_stdout(output):
            code = main(["cache", "prune", "--manager", "pnpm", "--apply", "--json"])
        self.assertEqual(code, 0)
        execute.assert_called_once()
        data = json.loads(output.getvalue())
        self.assertTrue(data["executed"])
        self.assertTrue(data["results"][0]["succeeded"])


if __name__ == "__main__":
    unittest.main()
