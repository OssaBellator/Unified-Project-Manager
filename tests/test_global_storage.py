from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.global_storage import GlobalStorageEntry, global_cache_storage, global_storage_summary


class GlobalStorageTests(unittest.TestCase):
    def test_go_cache_paths_use_exact_resolved_binary_and_measure_both_caches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = root / "mod"
            build = root / "build"
            mod.mkdir(); build.mkdir()
            (mod / "module.zip").write_bytes(b"m" * 11)
            (build / "artifact").write_bytes(b"b" * 13)
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, f"{mod}\n{build}\n", "")

            entries, skips = global_cache_storage(managers=("go",), run=run, which=lambda _name: "/toolchains/go")
            self.assertEqual(skips, [])
            self.assertEqual(calls[0], ["/toolchains/go", "env", "GOMODCACHE", "GOCACHE"])
            self.assertEqual({entry.category: entry.bytes for entry in entries}, {"module-cache": 11, "build-cache": 13})
            self.assertEqual(global_storage_summary(entries)["bytes"], 24)

    def test_native_store_providers_query_exact_manager_executables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {"npm": root / "npm", "pnpm": root / "pnpm", "uv": root / "uv"}
            for index, path in enumerate(paths.values(), start=1):
                path.mkdir()
                (path / "data").write_bytes(b"x" * index)
            calls = []

            def which(name):
                return f"/tools/{name}"

            def run(argv, **kwargs):
                calls.append(argv)
                manager = Path(argv[0]).name
                return subprocess.CompletedProcess(argv, 0, str(paths[manager]) + "\n", "")

            entries, skips = global_cache_storage(managers=("npm", "pnpm", "uv"), run=run, which=which)
            self.assertEqual(skips, [])
            self.assertIn(["/tools/npm", "get", "cache"], calls)
            self.assertIn(["/tools/pnpm", "store", "path"], calls)
            self.assertIn(["/tools/uv", "cache", "dir"], calls)
            by_manager = {entry.manager: entry for entry in entries}
            self.assertEqual(by_manager["npm"].category, "package-cache")
            self.assertEqual(by_manager["pnpm"].category, "content-store")
            self.assertEqual(by_manager["uv"].category, "package-cache")
            self.assertEqual(global_storage_summary(entries)["bytes"], 6)

    def test_cargo_cache_uses_documented_cargo_home_registry_and_git_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cargo_home = root / "cargo"
            registry = cargo_home / "registry"
            git = cargo_home / "git"
            registry.mkdir(parents=True); git.mkdir(parents=True)
            (registry / "crate").write_bytes(b"r" * 5)
            (git / "checkout").write_bytes(b"g" * 7)
            with patch.dict(os.environ, {"CARGO_HOME": str(cargo_home)}):
                entries, skips = global_cache_storage(managers=("cargo",), which=lambda _name: None)
            self.assertEqual(skips, [])
            self.assertEqual({entry.category: entry.bytes for entry in entries}, {"registry-cache": 5, "git-cache": 7})

    def test_missing_native_manager_is_explicit_skip(self) -> None:
        entries, skips = global_cache_storage(managers=("npm",), which=lambda _name: None)
        self.assertEqual(entries, [])
        self.assertEqual(skips[0].manager, "npm")
        self.assertIn("not available", skips[0].reason)

    def test_shared_hardlink_across_cache_roots_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod = root / "mod"; build = root / "build"
            mod.mkdir(); build.mkdir()
            first = mod / "shared"
            second = build / "shared"
            first.write_bytes(b"x" * 17)
            try:
                os.link(first, second)
            except OSError:
                self.skipTest("hardlinks unavailable")

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, f"{mod}\n{build}\n", "")

            entries, _ = global_cache_storage(managers=("go",), run=run, which=lambda _name: "/toolchains/go")
            self.assertEqual(global_storage_summary(entries)["bytes"], 17)

    def test_cache_storage_cli_labels_measurement_non_reclaimable(self) -> None:
        fake = [GlobalStorageEntry("go", "module-cache", "/cache/mod", 1024, 1)]
        output = io.StringIO()
        with patch("unified_project_manager.cache_entrypoint.global_cache_storage", return_value=(fake, [])), redirect_stdout(output):
            code = main(["cache", "storage", "--json"])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["scope"], "machine-wide-cache-storage")
        self.assertFalse(data["reclaimable"])
        self.assertEqual(data["summary"]["bytes"], 1024)


if __name__ == "__main__":
    unittest.main()
