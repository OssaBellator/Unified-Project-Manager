from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.cache_integrity import (
    CacheVerificationResult,
    plan_cache_verification,
    verify_go_module_cache,
)
from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main


class CacheIntegrityTests(unittest.TestCase):
    def test_go_cache_verification_uses_adjacent_temporary_modfile_and_cleans_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_mod = "module example.com/app\ngo 1.23\n"
            original_sum = "example.com/x v1.0.0 h1:abc\n"
            (root / "go.mod").write_text(original_mod, encoding="utf-8")
            (root / "go.sum").write_text(original_sum, encoding="utf-8")
            component = discover(root).components[0]
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                mod_arg = next(part for part in argv if part.startswith("-modfile="))
                temp_mod = Path(mod_arg.split("=", 1)[1])
                self.assertEqual(temp_mod.parent, root)
                self.assertEqual(temp_mod.read_text(encoding="utf-8"), original_mod)
                self.assertEqual(temp_mod.with_suffix(".sum").read_text(encoding="utf-8"), original_sum)
                temp_mod.with_suffix(".sum").write_text("changed temporary sum\n", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "all modules verified\n", "")

            result = verify_go_module_cache(component, root, run=run, which=lambda _name: "/toolchains/go")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0][0], "/toolchains/go")
            self.assertEqual(calls[0][1]["env"]["GOWORK"], "off")
            self.assertEqual((root / "go.mod").read_text(encoding="utf-8"), original_mod)
            self.assertEqual((root / "go.sum").read_text(encoding="utf-8"), original_sum)
            self.assertEqual(list(root.glob(".upm-verify-*")), [])

    def test_non_go_component_is_explicitly_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            components, skips = plan_cache_verification(discover(root))
            self.assertEqual(components, [])
            self.assertEqual(skips[0].ecosystem, "node")

    def test_public_cache_verify_json_has_explicit_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.23\n", encoding="utf-8")
            fake = CacheVerificationResult(
                ".:go",
                "go",
                "go",
                ("go", "mod", "verify", "--isolated-modfile"),
                0,
                "all modules verified\n",
                "",
            )
            output = io.StringIO()
            with patch("unified_project_manager.cache_entrypoint.verify_go_module_cache", return_value=fake), redirect_stdout(output):
                code = main(["verify", str(root), "--cache", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["scope"], "package-cache-content")
            self.assertTrue(data["results"][0]["succeeded"])


if __name__ == "__main__":
    unittest.main()
