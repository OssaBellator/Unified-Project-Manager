from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover


class DiscoveryTests(unittest.TestCase):
    def test_discovers_multiple_ecosystems_and_skips_install_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = root / "frontend"
            backend = root / "backend"
            engine = root / "engine"
            hidden = frontend / "node_modules" / "not-a-project"
            for directory in (frontend, backend, engine, hidden):
                directory.mkdir(parents=True)

            (frontend / "package.json").write_text(json.dumps({"packageManager": "pnpm@10.0.0", "dependencies": {"react": "^19.0.0"}}), encoding="utf-8")
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            (backend / "pyproject.toml").write_text('[project]\nname="backend"\nrequires-python=">=3.12"\ndependencies=["fastapi>=0.1"]\n', encoding="utf-8")
            (backend / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            (engine / "Cargo.toml").write_text('[package]\nname="engine"\nversion="0.1.0"\nrust-version="1.80"\n[dependencies]\nserde="1"\n', encoding="utf-8")
            (engine / "Cargo.lock").write_text("# lock\n", encoding="utf-8")
            (hidden / "package.json").write_text("{}", encoding="utf-8")

            graph = discover(root)

            self.assertEqual([(component.path.name, component.ecosystem, component.manager) for component in graph.components], [
                ("backend", "python", "uv"),
                ("engine", "rust", "cargo"),
                ("frontend", "node", "pnpm"),
            ])
            self.assertEqual(graph.components[0].toolchains[0].requirement, ">=3.12")
            self.assertEqual(graph.components[2].dependencies[0].name, "react")

    def test_node_manifest_manager_wins_but_records_lock_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")

            component = discover(root).components[0]
            self.assertEqual(component.manager, "pnpm")
            self.assertEqual(component.metadata["manager_from_lock"], "npm")

    def test_python_dependency_groups_and_poetry_tables_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname="x"\ndependencies=["httpx>=1"]\n'
                '[project.optional-dependencies]\ncli=["rich>=13"]\n'
                '[dependency-groups]\ndev=["pytest>=8"]\n'
                '[tool.poetry]\n[tool.poetry.dependencies]\npendulum="^3"\n',
                encoding="utf-8",
            )
            component = discover(root).components[0]
            found = {(dependency.name, dependency.scope) for dependency in component.dependencies}
            self.assertIn(("httpx", "runtime"), found)
            self.assertIn(("rich", "optional:cli"), found)
            self.assertIn(("pytest", "development:dev"), found)
            self.assertIn(("pendulum", "runtime"), found)
            self.assertEqual(component.manager, "poetry")


if __name__ == "__main__":
    unittest.main()
