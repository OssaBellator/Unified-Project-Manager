from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main
from unified_project_manager.yarn_graph import YarnGraphResult, parse_yarn_info, plan_yarn_graphs


_INFO = "\n".join([
    json.dumps({
        "value":"app@workspace:packages/app",
        "children":{
            "Version":"1.0.0",
            "Dependencies":[
                {"descriptor":"foo@npm:^1","locator":"foo@npm:1.2.3"},
            ],
        },
    }),
    json.dumps({"value":"foo@npm:1.2.3","children":{"Version":"1.2.3"}}),
]) + "\n"


class YarnWhyImpactEntrypointTests(unittest.TestCase):
    def _fixture(self, root: Path) -> YarnGraphResult:
        (root / "package.json").write_text(json.dumps({
            "name":"root",
            "version":"1.0.0",
            "private":True,
            "packageManager":"yarn@4.6.0",
            "workspaces":["packages/*"],
        }), encoding="utf-8")
        (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"name":"app","version":"1.0.0"}', encoding="utf-8")
        graph = discover(root)
        plan = plan_yarn_graphs(graph, selector="app")[0]
        packages, edges = parse_yarn_info(_INFO, plan.component)
        return YarnGraphResult(plan, packages, edges, 0, yarn_version="4.6.0")

    def test_member_impact_uses_yarn_locator_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._fixture(root)
            output = io.StringIO()

            with patch(
                "unified_project_manager.impact_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main([
                    "impact", "foo", str(root), "--native", "--json",
                    "--component", "app",
                ])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(len(data["impacts"]), 1)
            impact = data["impacts"][0]
            self.assertEqual(impact["provider"], "yarn-berry-resolution-graph")
            self.assertEqual(impact["scope"], "berry-resolution-graph")
            self.assertEqual(impact["component"], "packages/app:node")
            self.assertEqual(
                impact["root_paths"],
                [["app@workspace:packages/app", "foo@npm:1.2.3"]],
            )
            self.assertEqual(data["skips"], [])

    def test_member_why_matches_impact_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._fixture(root)
            output = io.StringIO()

            with patch(
                "unified_project_manager.why_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main([
                    "why", "foo", str(root), "--native", "--json",
                    "--component", "app",
                ])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(len(data["answers"]), 1)
            answer = data["answers"][0]
            self.assertEqual(answer["provider"], "yarn-berry-resolution-graph")
            self.assertEqual(answer["component"], "packages/app:node")
            self.assertEqual(
                answer["root_paths"],
                [["app@workspace:packages/app", "foo@npm:1.2.3"]],
            )
            self.assertEqual(data["skips"], [])


if __name__ == "__main__":
    unittest.main()
