from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.query import duplicates, why


class QueryTests(unittest.TestCase):
    def test_why_finds_dependency_across_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, version in (("a", "^1"), ("b", "^2")):
                directory = root / name
                directory.mkdir()
                (directory / "package.json").write_text(json.dumps({"packageManager": "npm@11", "dependencies": {"zod": version}}), encoding="utf-8")
                (directory / "package-lock.json").write_text("{}", encoding="utf-8")
            matches = why(discover(root), "zod")
            self.assertEqual([match["component"] for match in matches], ["a:node", "b:node"])

    def test_python_name_normalization_matches_pep_503_style_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("my_package==1\n", encoding="utf-8")
            matches = why(discover(root), "my-package")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["name"], "my_package")

    def test_duplicates_classifies_version_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, version in (("a", "^1"), ("b", "^2")):
                directory = root / name
                directory.mkdir()
                (directory / "package.json").write_text(json.dumps({"packageManager": "npm@11", "dependencies": {"zod": version}}), encoding="utf-8")
                (directory / "package-lock.json").write_text("{}", encoding="utf-8")
            groups = duplicates(discover(root))
            self.assertEqual(groups[0]["name"], "zod")
            self.assertEqual(groups[0]["classification"], "cross-component")
            self.assertTrue(groups[0]["version_divergence"])


if __name__ == "__main__":
    unittest.main()
