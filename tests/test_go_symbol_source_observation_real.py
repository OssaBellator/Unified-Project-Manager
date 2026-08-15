from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_go_symbol_runtime_fixture import (
    FIXTURE_APP_MODULE,
    FIXTURE_MODULE,
    FIXTURE_PACKAGE,
    FIXTURE_VERSION,
    fixture_go_environment,
    prepare_module_cache,
    write_runtime_fixture,
)
from unified_project_manager.go_symbol_source_observation import (
    build_go_symbol_source_observation_plan,
    execute_go_symbol_source_observation,
)


class GoSymbolSourceObservationRealTests(unittest.TestCase):
    def _snapshot(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    @unittest.skipUnless(shutil.which("go"), "Go executable is not available")
    def test_real_go_observes_selected_sources_offline_without_project_mutation(self) -> None:
        go = shutil.which("go")
        self.assertIsNotNone(go)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")
            prepared = prepare_module_cache(fixture, go_executable=go)
            self.assertEqual(prepared.returncode, 0, prepared.stderr or prepared.stdout)
            self.assertTrue((fixture.project / "go.sum").is_file())
            before = self._snapshot(fixture.project)

            plan = build_go_symbol_source_observation_plan(fixture.project, executable=go)
            isolated = fixture_go_environment(fixture)
            inherited = {
                "GOMODCACHE": isolated["GOMODCACHE"],
                "GOCACHE": isolated["GOCACHE"],
            }
            with patch.dict(os.environ, inherited, clear=False):
                result = execute_go_symbol_source_observation(plan)

            self.assertTrue(result.succeeded, result.error or result.stderr)
            observation = result.observation
            self.assertIsNotNone(observation)
            self.assertTrue(observation.build_environment.get("GOOS"))
            self.assertTrue(observation.build_environment.get("GOARCH"))
            self.assertTrue(observation.build_environment.get("GOVERSION"))
            self.assertEqual(observation.to_dict()["freshness"], "not-established")
            self.assertEqual(observation.to_dict()["govulncheck_equivalence"], "not-established")

            packages = {package.import_path: package for package in observation.packages}
            self.assertIn(FIXTURE_APP_MODULE, packages)
            self.assertIn(FIXTURE_PACKAGE, packages)
            app = packages[FIXTURE_APP_MODULE]
            dep = packages[FIXTURE_PACKAGE]
            self.assertFalse(app.dep_only)
            self.assertTrue(app.module.main)
            self.assertIn("main.go", app.selected_files)
            self.assertTrue(dep.dep_only)
            self.assertEqual(dep.module.path, FIXTURE_MODULE)
            self.assertEqual(dep.module.version, FIXTURE_VERSION)
            self.assertFalse(dep.module.replaced)
            self.assertIn("dep.go", dep.selected_files)
            self.assertEqual(observation.root_packages, (FIXTURE_APP_MODULE,))

            self.assertEqual(self._snapshot(fixture.project), before)


if __name__ == "__main__":
    unittest.main()
