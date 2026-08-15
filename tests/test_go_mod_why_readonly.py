from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("go"), "Go executable is not available")
class GoModWhyReadonlyTests(unittest.TestCase):
    def test_go_mod_why_m_is_project_state_read_only_with_local_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            dep = root / "dep"
            app.mkdir()
            (dep / "pkg").mkdir(parents=True)

            (dep / "go.mod").write_text(
                "module example.com/dep\ngo 1.23\n",
                encoding="utf-8",
            )
            (dep / "pkg" / "pkg.go").write_text(
                "package pkg\nconst X = 1\n",
                encoding="utf-8",
            )
            (app / "go.mod").write_text(
                "module example.com/app\n"
                "go 1.23\n"
                "require example.com/dep v0.0.0\n"
                "replace example.com/dep => ../dep\n",
                encoding="utf-8",
            )
            (app / "main.go").write_text(
                'package main\nimport _ "example.com/dep/pkg"\nfunc main() {}\n',
                encoding="utf-8",
            )
            (app / "go.sum").write_bytes(b"")

            before_mod = (app / "go.mod").read_bytes()
            before_sum = (app / "go.sum").read_bytes()
            environment = dict(os.environ)
            environment["GOPROXY"] = "off"
            environment["GOWORK"] = "off"

            completed = subprocess.run(
                [shutil.which("go") or "go", "mod", "why", "-m", "example.com/dep"],
                cwd=app,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            self.assertIn("# example.com/dep", completed.stdout)
            self.assertIn("example.com/dep/pkg", completed.stdout)
            self.assertEqual((app / "go.mod").read_bytes(), before_mod)
            self.assertEqual((app / "go.sum").read_bytes(), before_sum)


if __name__ == "__main__":
    unittest.main()
