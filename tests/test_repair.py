from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.doctor import diagnose
from unified_project_manager.repair import plan_repairs


class RepairTests(unittest.TestCase):
    def test_node_installed_drift_maps_to_native_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {"": {}, "node_modules/foo": {"version": "1.0.0"}},
            }), encoding="utf-8")
            package = root / "node_modules" / "foo"
            package.mkdir(parents=True)
            (package / "package.json").write_text('{"name":"foo","version":"2.0.0"}', encoding="utf-8")
            graph = discover(root)
            report = diagnose(graph, which=lambda _name: "/bin/tool", deep=True)
            plans = plan_repairs(graph, report)
            self.assertEqual([plan.argv for plan in plans], [("npm", "ci")])

    def test_python_installed_drift_maps_to_locked_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('[project]\nname="x"\n[tool.uv]\n', encoding="utf-8")
            (root / "uv.lock").write_text('''version = 1

[[package]]
name = "httpx"
version = "1.0.0"
''', encoding="utf-8")
            metadata = root / ".venv" / "lib" / "python3.13" / "site-packages" / "httpx-2.0.0.dist-info" / "METADATA"
            metadata.parent.mkdir(parents=True)
            metadata.write_text("Name: httpx\nVersion: 2.0.0\n", encoding="utf-8")
            graph = discover(root)
            report = diagnose(graph, which=lambda _name: "/bin/tool", deep=True)
            plans = plan_repairs(graph, report)
            self.assertEqual([plan.argv for plan in plans], [("uv", "sync", "--locked")])

    def test_structural_errors_do_not_generate_unsafe_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            graph = discover(root)
            report = diagnose(graph, which=lambda _name: "/bin/tool", deep=True)
            self.assertEqual(plan_repairs(graph, report), [])


if __name__ == "__main__":
    unittest.main()
