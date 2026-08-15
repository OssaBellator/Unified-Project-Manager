from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.entrypoint import main


_LOCK = '''
version = 1

[[package]]
name = "root"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "foo", version = "1.0.0" }]

[[package]]
name = "app"
version = "0.1.0"
source = { editable = "packages/app" }
dependencies = [{ name = "bar", version = "1.0.0" }]

[[package]]
name = "sibling"
version = "0.1.0"
source = { editable = "packages/sibling" }
dependencies = [{ name = "baz", version = "1.0.0" }]

[[package]]
name = "foo"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "bar"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "baz"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
'''


class UvWorkspaceSbomRoutingTests(unittest.TestCase):
    def _project(self, path: Path, name: str, extra: str = "") -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\n{extra}', encoding="utf-8"
        )

    def _workspace(self, root: Path) -> None:
        self._project(root, "root", '[tool.uv.workspace]\nmembers=["packages/*"]\n')
        self._project(root / "packages" / "app", "app")
        self._project(root / "packages" / "sibling", "sibling")
        (root / "uv.lock").write_text(_LOCK, encoding="utf-8")

    def test_selected_member_cyclonedx_uses_shared_lock_without_sibling_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["sbom", str(root), "--native", "--component", "app"])
            document = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            purls = {component.get("purl") for component in document.get("components", [])}
            self.assertEqual(purls, {"pkg:pypi/bar@1.0.0"})
            bar = document["components"][0]
            self.assertIn(
                {"name": "upm:uv:scope-component", "value": "packages/app:python"},
                bar.get("properties", []),
            )

    def test_selected_member_spdx_uses_same_shared_lock_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            output = io.StringIO()

            with redirect_stdout(output):
                code = main([
                    "sbom", str(root), "--native", "--component", "app",
                    "--format", "spdx",
                ])
            document = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            purls = {
                external["referenceLocator"]
                for package in document.get("packages", [])
                for external in package.get("externalRefs", [])
                if external.get("referenceType") == "purl"
            }
            self.assertEqual(purls, {"pkg:pypi/bar@1.0.0"})
            self.assertNotIn("foo", {package.get("name") for package in document.get("packages", [])})
            self.assertNotIn("baz", {package.get("name") for package in document.get("packages", [])})

    def test_selected_root_does_not_seed_entire_shared_lock_from_static_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["sbom", str(root), "--native", "--component", "root"])
            document = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            purls = {component.get("purl") for component in document.get("components", [])}
            self.assertEqual(purls, {"pkg:pypi/foo@1.0.0"})


if __name__ == "__main__":
    unittest.main()
