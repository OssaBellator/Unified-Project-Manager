from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from support_go_symbol_runtime_fixture import (
    FIXTURE_APP_MODULE,
    FIXTURE_MODULE,
    FIXTURE_VERSION,
    prepare_module_cache,
    verify_offline_module_available,
    write_runtime_fixture,
)
from support_go_vulndb_fixture import FIXTURE_ID, FIXTURE_PACKAGE, FIXTURE_SYMBOL


class GoSymbolRuntimeFixtureTests(unittest.TestCase):
    def _digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_writes_local_proxy_project_db_and_isolated_caches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")

            self.assertTrue((fixture.project / "go.mod").is_file())
            self.assertTrue((fixture.project / "main.go").is_file())
            self.assertTrue((fixture.vulnerability_db / "index" / "modules.json").is_file())
            self.assertTrue((fixture.vulnerability_db / "ID" / f"{FIXTURE_ID}.json").is_file())
            self.assertTrue(fixture.module_cache.is_dir())
            self.assertTrue(fixture.build_cache.is_dir())

            version_dir = fixture.proxy / FIXTURE_MODULE / "@v"
            self.assertEqual((version_dir / "list").read_text(encoding="utf-8"), FIXTURE_VERSION + "\n")
            info = json.loads((version_dir / f"{FIXTURE_VERSION}.info").read_text(encoding="utf-8"))
            self.assertEqual(info["Version"], FIXTURE_VERSION)
            self.assertTrue((version_dir / f"{FIXTURE_VERSION}.mod").is_file())
            self.assertTrue((version_dir / f"{FIXTURE_VERSION}.zip").is_file())

    def test_proxy_zip_uses_required_module_version_prefix_and_expected_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")
            zip_path = fixture.proxy / FIXTURE_MODULE / "@v" / f"{FIXTURE_VERSION}.zip"
            prefix = f"{FIXTURE_MODULE}@{FIXTURE_VERSION}/"
            with zipfile.ZipFile(zip_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, [prefix + "go.mod", prefix + "pkg/dep.go"])
                self.assertTrue(all(name.startswith(prefix) for name in names))
                source = archive.read(prefix + "pkg/dep.go").decode("utf-8")
                self.assertIn(f"func {FIXTURE_SYMBOL}()", source)

    def test_project_requires_versioned_dependency_without_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")
            go_mod = (fixture.project / "go.mod").read_text(encoding="utf-8")
            main_go = (fixture.project / "main.go").read_text(encoding="utf-8")

            self.assertIn(f"module {FIXTURE_APP_MODULE}", go_mod)
            self.assertIn(f"require {FIXTURE_MODULE} {FIXTURE_VERSION}", go_mod)
            self.assertNotIn("replace ", go_mod)
            self.assertIn(f'"{FIXTURE_PACKAGE}"', main_go)
            self.assertIn(f"dep.{FIXTURE_SYMBOL}()", main_go)

    def test_fixture_generation_is_deterministic_for_proxy_and_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = write_runtime_fixture(root / "one")
            two = write_runtime_fixture(root / "two")
            relative_files = [
                "project/go.mod",
                "project/main.go",
                f"proxy/{FIXTURE_MODULE}/@v/list",
                f"proxy/{FIXTURE_MODULE}/@v/{FIXTURE_VERSION}.info",
                f"proxy/{FIXTURE_MODULE}/@v/{FIXTURE_VERSION}.mod",
                f"proxy/{FIXTURE_MODULE}/@v/{FIXTURE_VERSION}.zip",
                "vulndb/index/db.json",
                "vulndb/index/modules.json",
                "vulndb/index/vulns.json",
                f"vulndb/ID/{FIXTURE_ID}.json",
            ]
            for relative in relative_files:
                with self.subTest(relative=relative):
                    self.assertEqual(
                        self._digest(one.root / relative),
                        self._digest(two.root / relative),
                    )

    @unittest.skipUnless(shutil.which("go"), "Go executable is not available")
    def test_real_go_populates_isolated_cache_from_file_proxy_then_resolves_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")
            before_mod = (fixture.project / "go.mod").read_bytes()
            before_main = (fixture.project / "main.go").read_bytes()

            downloaded = prepare_module_cache(fixture)
            self.assertEqual(downloaded.returncode, 0, downloaded.stderr or downloaded.stdout)
            data = json.loads(downloaded.stdout)
            self.assertEqual(data["Path"], FIXTURE_MODULE)
            self.assertEqual(data["Version"], FIXTURE_VERSION)
            self.assertTrue(Path(data["Dir"]).is_dir())
            self.assertTrue(Path(data["Zip"]).is_file())
            self.assertTrue((fixture.project / "go.sum").is_file())

            offline = verify_offline_module_available(fixture)
            self.assertEqual(offline.returncode, 0, offline.stderr or offline.stdout)
            self.assertIn(FIXTURE_PACKAGE, offline.stdout.splitlines())
            self.assertIn(FIXTURE_APP_MODULE, offline.stdout.splitlines())
            self.assertEqual((fixture.project / "go.mod").read_bytes(), before_mod)
            self.assertEqual((fixture.project / "main.go").read_bytes(), before_main)


if __name__ == "__main__":
    unittest.main()
