from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.root_entrypoint import main


class FleetProviderEntrypointTests(unittest.TestCase):
    def _uv_project(self, root: Path, name: str, dependency_name: str, version: str) -> None:
        (root / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\n[tool.uv]\n', encoding="utf-8"
        )
        (root / "uv.lock").write_text(f'''
version = 1
[[package]]
name = "{name}"
version = "0.1.0"
source = {{ editable = "." }}
dependencies = [{{ name = "{dependency_name}", version = "{version}" }}]

[[package]]
name = "{dependency_name}"
version = "{version}"
source = {{ registry = "https://pypi.org/simple" }}
''', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_native_fleet_inventory_routes_uv_provider_without_external_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / "one"
            two = root / "two"
            one.mkdir()
            two.mkdir()
            self._uv_project(one, "one", "Foo_Bar", "1.0.0")
            self._uv_project(two, "two", "foo-bar", "2.0.0")
            registry = root / "projects.json"
            registry.write_text(json.dumps({
                "version": 1,
                "projects": [str(one), str(two)],
            }), encoding="utf-8")

            code, data = self._json([
                "projects", "inventory", "--native", "--registry", str(registry), "--json"
            ])

            self.assertEqual(code, 0)
            self.assertEqual(len(data["inventory"]), 2)
            self.assertEqual({item["provider"] for item in data["inventory"]}, {"uv-lock"})
            self.assertEqual({item["scope"] for item in data["inventory"]}, {"universal-lock-package"})
            self.assertEqual(data["failures"], [])

    def test_native_fleet_duplicates_normalize_python_names_and_never_claim_reclaimable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / "one"
            two = root / "two"
            one.mkdir()
            two.mkdir()
            self._uv_project(one, "one", "Foo_Bar", "1.0.0")
            self._uv_project(two, "two", "foo-bar", "2.0.0")
            registry = root / "projects.json"
            registry.write_text(json.dumps({
                "version": 1,
                "projects": [str(one), str(two)],
            }), encoding="utf-8")

            code, data = self._json([
                "projects", "duplicates", "--native", "--registry", str(registry), "--json"
            ])

            self.assertEqual(code, 0)
            self.assertFalse(data["reclaimable"])
            self.assertEqual(len(data["duplicates"]), 1)
            group = data["duplicates"][0]
            self.assertEqual(group["normalized_name"], "foo-bar")
            self.assertEqual(group["projects"], 2)
            self.assertTrue(group["version_divergence"])
            self.assertFalse(group["reclaimable"])
            self.assertEqual(group["versions"], ["1.0.0", "2.0.0"])


if __name__ == "__main__":
    unittest.main()
