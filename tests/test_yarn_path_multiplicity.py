from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.yarn_graph import YarnGraphPlan, YarnGraphResult, parse_yarn_info
from unified_project_manager.yarn_impact import analyze_yarn_impact


def _ndjson(records: list[dict]) -> str:
    return "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n"


_INFO = _ndjson([
    {
        "value":"app@workspace:.",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"a@npm:^1","locator":"a@npm:1.0.0"},
                {"descriptor":"b@npm:^1","locator":"b@npm:1.0.0"},
            ],
        },
    },
    {
        "value":"a@npm:1.0.0",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"shared@npm:^2","locator":"shared@npm:2.0.0"},
            ],
        },
    },
    {
        "value":"b@npm:1.0.0",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"shared@npm:^2","locator":"shared@npm:2.0.0"},
            ],
        },
    },
    {"value":"shared@npm:2.0.0","children":{"Version":"2.0.0"}},
])


class YarnPathMultiplicityTests(unittest.TestCase):
    def _result(self, root: Path) -> YarnGraphResult:
        packages, edges = parse_yarn_info(_INFO, ".:node")
        return YarnGraphResult(
            YarnGraphPlan(".:node", root, root, True),
            packages,
            edges,
            0,
            yarn_version="4.6.0",
        )

    def test_analyzer_keeps_distinct_paths_to_same_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            impact = analyze_yarn_impact(self._result(Path(temporary)), "shared")[0]
            self.assertEqual(
                set(impact.root_paths),
                {
                    ("app@workspace:.", "a@npm:1.0.0", "shared@npm:2.0.0"),
                    ("app@workspace:.", "b@npm:1.0.0", "shared@npm:2.0.0"),
                },
            )
            self.assertFalse(impact.paths_truncated)
            self.assertEqual(
                set(impact.direct_dependents),
                {"a@npm:1.0.0", "b@npm:1.0.0"},
            )

    def test_path_budget_is_explicit_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            impact = analyze_yarn_impact(
                self._result(Path(temporary)),
                "shared",
                max_paths_per_target=1,
            )[0]
            self.assertEqual(len(impact.root_paths), 1)
            self.assertTrue(impact.paths_truncated)

    def test_public_impact_json_returns_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(
                '{"name":"app","version":"1.0.0","packageManager":"yarn@4.6.0"}',
                encoding="utf-8",
            )
            (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
            result = self._result(root)
            output = io.StringIO()
            with patch(
                "unified_project_manager.impact_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main(["impact", "shared", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(len(data["impacts"]), 1)
            self.assertEqual(len(data["impacts"][0]["root_paths"]), 2)
            self.assertFalse(data["impacts"][0]["paths_truncated"])

    def test_public_why_json_returns_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(
                '{"name":"app","version":"1.0.0","packageManager":"yarn@4.6.0"}',
                encoding="utf-8",
            )
            (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
            result = self._result(root)
            output = io.StringIO()
            with patch(
                "unified_project_manager.why_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main(["why", "shared", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(len(data["answers"]), 1)
            self.assertEqual(len(data["answers"][0]["root_paths"]), 2)
            self.assertFalse(data["answers"][0]["paths_truncated"])


if __name__ == "__main__":
    unittest.main()
