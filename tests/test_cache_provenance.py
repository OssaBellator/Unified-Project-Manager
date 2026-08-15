from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.cache_provenance import collect_cache_provenance
from unified_project_manager.cargo_graph import CargoGraphResult, CargoPackage
from unified_project_manager.global_storage import GlobalStorageEntry
from unified_project_manager.native_graph import NativeGraphResult, NativeModule
from unified_project_manager.root_entrypoint import main


class CacheProvenanceTests(unittest.TestCase):
    def _mixed_project(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
        (root / "Cargo.toml").write_text(
            '[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8"
        )
        (root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")

    def test_collects_go_and_cargo_attribution_without_reclaim_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            self._mixed_project(project)

            gomodcache = root / "gomodcache"
            go_source = gomodcache / "example.com" / "foo@v1.0.0"
            go_source.mkdir(parents=True)
            (go_source / "foo.go").write_bytes(b"x" * 10)
            go_download = gomodcache / "cache" / "download" / "example.com" / "foo" / "@v"
            go_download.mkdir(parents=True)
            (go_download / "v1.0.0.zip").write_bytes(b"x" * 5)

            cargo_home = root / "cargo-home"
            cargo_source = cargo_home / "registry" / "src" / "index" / "serde-1.0.0"
            cargo_source.mkdir(parents=True)
            (cargo_source / "lib.rs").write_bytes(b"x" * 7)
            (cargo_source / "Cargo.toml").write_text("[package]\nname='serde'\nversion='1.0.0'\n", encoding="utf-8")
            (cargo_home / "git").mkdir(parents=True)
            cargo_attributed = sum(
                path.stat().st_size for path in cargo_source.iterdir() if path.is_file()
            )

            entries = [
                GlobalStorageEntry("go", "module-cache", str(gomodcache), 20, 3),
                GlobalStorageEntry("go", "build-cache", str(root / "gobuild"), 100, 1),
                GlobalStorageEntry("cargo", "registry-cache", str(cargo_home / "registry"), cargo_attributed + 4, 3),
                GlobalStorageEntry("cargo", "git-cache", str(cargo_home / "git"), 0, 0),
            ]

            def storage_probe(*, managers):
                self.assertEqual(tuple(managers), ("go", "cargo"))
                return entries, []

            def execute_go(plan):
                return NativeGraphResult(
                    plan,
                    [NativeModule(
                        component=plan.component,
                        name="example.com/foo",
                        version="v1.0.0",
                        directory=str(go_source),
                    )],
                    [],
                    0,
                )

            def execute_cargo(plan):
                return CargoGraphResult(
                    plan,
                    [CargoPackage(
                        component=plan.component,
                        package_id="registry+https://github.com/rust-lang/crates.io-index#serde@1.0.0",
                        name="serde",
                        version="1.0.0",
                        source="registry+https://github.com/rust-lang/crates.io-index",
                        manifest_path=str(cargo_source / "Cargo.toml"),
                        workspace_member=False,
                        workspace_default_member=False,
                    )],
                    [],
                    0,
                )

            report = collect_cache_provenance(
                roots=[project],
                closed_universe=True,
                storage_probe=storage_probe,
                execute_go=execute_go,
                execute_cargo=execute_cargo,
            )

            self.assertTrue(report["project_universe"]["closed"])
            self.assertTrue(report["observation_complete"])
            self.assertFalse(report["unattributed_means_unused"])
            self.assertIsNone(report["reclaimable_bytes"])
            self.assertFalse(report["reclaimable"])

            managers = {item["manager"]: item for item in report["managers"]}
            self.assertEqual(managers["go"]["total_bytes"], 20)
            self.assertEqual(managers["go"]["attributed_bytes"], 15)
            self.assertEqual(managers["go"]["unattributed_bytes"], 5)
            self.assertEqual(
                {group["cache_kind"] for group in managers["go"]["groups"]},
                {"module-source", "download-zip"},
            )
            # Go build cache is intentionally outside selected-module attribution.
            self.assertNotEqual(managers["go"]["total_bytes"], 120)

            cargo = managers["cargo"]
            self.assertEqual(cargo["total_bytes"], cargo_attributed + 4)
            self.assertEqual(cargo["attributed_bytes"], cargo_attributed)
            self.assertEqual(cargo["unattributed_bytes"], 4)
            self.assertEqual({group["cache_kind"] for group in cargo["groups"]}, {"registry-source"})
            self.assertTrue(all(not group["reclaimable"] for group in cargo["groups"]))

    def test_missing_project_invalidates_closed_universe_assertion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            self._mixed_project(project)
            missing = root / "missing"

            report = collect_cache_provenance(
                roots=[project, missing],
                managers=(),
                closed_universe=True,
                storage_probe=lambda *, managers: ([], []),
            )

            self.assertTrue(report["project_universe"]["closed_asserted"])
            self.assertFalse(report["project_universe"]["closed"])
            self.assertEqual(report["project_universe"]["missing"], [str(missing)])
            self.assertFalse(report["observation_complete"])

    def test_provider_failure_is_separate_from_project_universe_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            gomodcache = root / "gomodcache"
            gomodcache.mkdir()

            def execute_go(plan):
                return NativeGraphResult(plan, [], [], 2, stderr="offline module data missing")

            report = collect_cache_provenance(
                roots=[project],
                managers=("go",),
                closed_universe=True,
                storage_probe=lambda *, managers: (
                    [GlobalStorageEntry("go", "module-cache", str(gomodcache), 0, 0)], []
                ),
                execute_go=execute_go,
            )

            self.assertTrue(report["project_universe"]["closed"])
            self.assertFalse(report["observation_complete"])
            self.assertEqual(len(report["provider_failures"]), 1)
            self.assertEqual(report["provider_failures"][0]["error"], "offline module data missing")
            self.assertFalse(report["reclaimable"])

    def test_unlocked_cargo_component_is_an_explicit_incomplete_provider_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / "Cargo.toml").write_text(
                '[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8"
            )
            cargo_home = root / "cargo-home"
            (cargo_home / "registry").mkdir(parents=True)
            (cargo_home / "git").mkdir(parents=True)

            with patch("unified_project_manager.cache_provenance.execute_cargo_graph") as execute:
                report = collect_cache_provenance(
                    roots=[project],
                    managers=("cargo",),
                    closed_universe=True,
                    storage_probe=lambda *, managers: (
                        [
                            GlobalStorageEntry("cargo", "registry-cache", str(cargo_home / "registry"), 0, 0),
                            GlobalStorageEntry("cargo", "git-cache", str(cargo_home / "git"), 0, 0),
                        ],
                        [],
                    ),
                )

            execute.assert_not_called()
            self.assertTrue(report["project_universe"]["closed"])
            self.assertFalse(report["observation_complete"])
            self.assertEqual(len(report["provider_skips"]), 1)
            self.assertIn("locked Cargo provider plan", report["provider_skips"][0]["reason"])
            self.assertFalse(report["reclaimable"])

    def test_public_cli_routes_json_without_reclaim_claim(self) -> None:
        report = {
            "scope": "registered-project-cache-provenance",
            "managers": [],
            "project_universe": {
                "registered": 0,
                "observed": 0,
                "missing": [],
                "discovery_failures": [],
                "closed_asserted": False,
                "closed": False,
            },
            "observation_complete": True,
            "provider_failures": [],
            "provider_skips": [],
            "attribution_skips": [],
            "storage_skips": [],
            "unattributed_means_unused": False,
            "reclaimable_bytes": None,
            "reclaimable": False,
        }
        output = io.StringIO()
        with patch(
            "unified_project_manager.cache_entrypoint.collect_cache_provenance",
            return_value=report,
        ) as collect, redirect_stdout(output):
            code = main(["cache", "provenance", "--json"])

        self.assertEqual(code, 0)
        collect.assert_called_once()
        data = json.loads(output.getvalue())
        self.assertEqual(data["scope"], "registered-project-cache-provenance")
        self.assertFalse(data["unattributed_means_unused"])
        self.assertIsNone(data["reclaimable_bytes"])
        self.assertFalse(data["reclaimable"])


if __name__ == "__main__":
    unittest.main()
