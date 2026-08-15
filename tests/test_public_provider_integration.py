from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.root_entrypoint import main


_LOCK = '''
version = 1
requires-python = ">=3.12"

[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [
  { name = "foo", version = "1.0.0", marker = "sys_platform == 'linux'" },
  { name = "bar" },
]

[[package]]
name = "bar"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
  { name = "foo" },
]

[[package]]
name = "foo"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "foo"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
'''


class PublicProviderIntegrationTests(unittest.TestCase):
    def _uv_project(self, root: Path) -> None:
        (root / "pyproject.toml").write_text(
            '[project]\nname="app"\nversion="0.1.0"\n[tool.uv]\n', encoding="utf-8"
        )
        (root / "uv.lock").write_text(_LOCK, encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_native_graph_routes_static_uv_lock_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._uv_project(root)

            code, data = self._json(["graph", str(root), "--native", "--json"])

            self.assertEqual(code, 0)
            result = next(item for item in data["results"] if item["provider"] == "uv-lock")
            self.assertEqual(result["plan"]["source"], "uv.lock")
            self.assertFalse(result["plan"]["network"])
            self.assertFalse(result["plan"]["execution"])
            self.assertEqual(result["ambiguous_edges"], 1)
            marker_edges = [edge for edge in result["edges"] if edge["marker"]]
            self.assertEqual(marker_edges[0]["marker"], "sys_platform == 'linux'")

    def test_native_impact_and_why_route_uv_without_guessing_forks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._uv_project(root)

            impact_code, impact = self._json(["impact", "foo", str(root), "--native", "--json"])
            why_code, why = self._json(["why", "foo", str(root), "--native", "--json"])

            self.assertEqual(impact_code, 0)
            self.assertEqual(why_code, 0)
            uv_impacts = [item for item in impact["impacts"] if item["provider"] == "uv-lock"]
            self.assertEqual({item["version"] for item in uv_impacts}, {"1.0.0", "2.0.0"})
            self.assertTrue(all(item["ambiguous_references"] == 1 for item in uv_impacts))
            uv_answers = [item for item in why["answers"] if item["provider"] == "uv-lock"]
            self.assertEqual(len(uv_answers), 2)
            self.assertTrue(all(item["scope"] == "universal-lock-graph" for item in uv_answers))

    def test_sbom_format_spdx_is_public_without_native_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._uv_project(root)

            code, document = self._json(["sbom", str(root), "--format", "spdx"])

            self.assertEqual(code, 0)
            self.assertEqual(document["spdxVersion"], "SPDX-2.3")
            self.assertEqual(document["dataLicense"], "CC0-1.0")
            self.assertTrue(document["packages"])

    def test_native_cyclonedx_records_uv_ambiguous_edge_omission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._uv_project(root)

            code, document = self._json(["sbom", str(root), "--native", "--json"])

            self.assertEqual(code, 0)
            bar = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/bar@1.0.0")
            properties = {(item["name"], item["value"]) for item in bar.get("properties", [])}
            self.assertIn(("upm:uv:identity-kind", "uv-lock-universal"), properties)
            self.assertIn(("upm:uv:ambiguous-edges-omitted", "1"), properties)


if __name__ == "__main__":
    unittest.main()
