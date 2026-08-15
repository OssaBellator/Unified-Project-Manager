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

            entries, skips = global_cache_storage(run=run, which=lambda _name: "/toolchains/go")
            self.assertEqual(skips, [])
            self.assertEqual(calls[0], ["/toolchains/go", "env", "GOMODCACHE", "GOCACHE"])
            self.assertEqual({entry.category: entry.bytes for entry in entries}, {"module-cache": 11, "build-cache": 13})
            self.assertEqual(global_storage_summary(entries)["bytes"], 24)

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

            entries, _ = global_cache_storage(run=run, which=lambda _name: "/toolchains/go")
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
