from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.root_entrypoint import main


class StatusEvidenceIntegrationTests(unittest.TestCase):
    def test_status_json_includes_persisted_evidence_and_provider_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(
                '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
            )
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["status", str(root), "--json"])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["advisory_evidence"]["state"], "absent")
            self.assertEqual(data["mutation_receipts"]["state"], "absent")
            self.assertEqual(data["relationship_providers"]["supported_components"], 1)
            self.assertFalse(data["local_evidence"]["network_executed"])
            self.assertFalse(data["local_evidence"]["scanner_execution"])
            self.assertEqual(data["summary"]["blockers"], [])

    def test_workspace_error_is_status_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(
                '{"packageManager":"npm@11","workspaces":["packages/*"]}', encoding="utf-8"
            )
            (root / "package-lock.json").write_text(
                '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
            )
            first = root / "packages" / "a"
            second = root / "packages" / "b"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "package.json").write_text('{"name":"same"}', encoding="utf-8")
            (second / "package.json").write_text('{"name":"same"}', encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["status", str(root), "--json"])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertIn("workspace-errors", data["summary"]["blockers"])
            self.assertTrue(data["workspace_health"])


if __name__ == "__main__":
    unittest.main()
