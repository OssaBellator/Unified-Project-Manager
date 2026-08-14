from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.query import resolved_duplicates, why_resolved


class ResolvedInventoryTests(unittest.TestCase):
    def test_npm_lockfile_exposes_resolved_locations_and_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/foo": {"version": "1.0.0"},
                    "node_modules/parent/node_modules/foo": {"version": "2.0.0"},
                },
            }), encoding="utf-8")
            component = discover(root).components[0]
            self.assertEqual([(item.name, item.version) for item in component.resolved_packages], [("foo", "1.0.0"), ("foo", "2.0.0")])
            groups = resolved_duplicates(discover(root))
            self.assertTrue(groups[0]["version_divergence"])
            self.assertEqual(groups[0]["classification"], "multiple-resolved-versions")

    def test_cargo_lockfile_exposes_multiple_resolved_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('''version = 4

[[package]]
name = "itoa"
version = "1.0.1"

[[package]]
name = "itoa"
version = "1.0.2"
''', encoding="utf-8")
            groups = resolved_duplicates(discover(root))
            self.assertEqual(groups[0]["name"], "itoa")
            self.assertEqual({item["version"] for item in groups[0]["occurrences"]}, {"1.0.1", "1.0.2"})

    def test_uv_lockfile_exposes_resolved_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('[project]\nname="x"\n[tool.uv]\n', encoding="utf-8")
            (root / "uv.lock").write_text('''version = 1

[[package]]
name = "anyio"
version = "4.1.0"

[[package]]
name = "anyio"
version = "4.2.0"
''', encoding="utf-8")
            groups = resolved_duplicates(discover(root))
            self.assertEqual(groups[0]["ecosystem"], "python")
            self.assertTrue(groups[0]["version_divergence"])

    def test_resolved_why_returns_versions_and_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/foo": {"version": "1.2.3", "resolved": "https://registry.example/foo.tgz"},
                },
            }), encoding="utf-8")
            matches = why_resolved(discover(root), "foo")
            self.assertEqual(matches[0]["version"], "1.2.3")
            self.assertEqual(matches[0]["location"], "node_modules/foo")
            self.assertEqual(matches[0]["source"], "https://registry.example/foo.tgz")


if __name__ == "__main__":
    unittest.main()
