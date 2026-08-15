from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.root_entrypoint import main


class FleetStatusEntrypointTests(unittest.TestCase):
    def _clean_npm_project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","packageManager":"npm@11"}', encoding="utf-8"
        )
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{"name":"app"}}}', encoding="utf-8"
        )

    def _broken_workspace(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"root","packageManager":"npm@11","workspaces":["packages/*"]}',
            encoding="utf-8",
        )
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{"name":"root"}}}', encoding="utf-8"
        )
        one = root / "packages" / "one"
        two = root / "packages" / "two"
        one.mkdir(parents=True)
        two.mkdir(parents=True)
        (one / "package.json").write_text('{"name":"duplicate"}', encoding="utf-8")
        (two / "package.json").write_text('{"name":"duplicate"}', encoding="utf-8")

    def test_fleet_status_combines_local_evidence_and_missing_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clean = root / "clean"
            broken = root / "broken"
            missing = root / "missing"
            clean.mkdir()
            broken.mkdir()
            self._clean_npm_project(clean)
            self._broken_workspace(broken)
            registry = root / "projects.json"
            registry.write_text(json.dumps({
                "version": 1,
                "projects": [str(clean), str(broken), str(missing)],
            }), encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                code = main([
                    "projects", "status", "--registry", str(registry), "--json"
                ])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["projects"], 3)
            self.assertEqual(data["summary"]["clear"], 1)
            self.assertEqual(data["summary"]["blocked"], 2)
            self.assertEqual(data["summary"]["missing"], 1)
            self.assertFalse(data["summary"]["network_executed"])
            self.assertFalse(data["summary"]["scanner_execution"])
            self.assertFalse(data["summary"]["native_relationship_execution"])

            by_path = {item["path"]: item for item in data["projects"]}
            self.assertFalse(by_path[str(clean)]["blocked"])
            self.assertIn("workspace-errors", by_path[str(broken)]["blockers"])
            self.assertEqual(by_path[str(missing)]["blockers"], ["project-missing"])


if __name__ == "__main__":
    unittest.main()
