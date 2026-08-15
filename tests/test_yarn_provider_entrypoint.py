from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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


class YarnProviderEntrypointTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
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
        return member

    def test_member_preview_is_root_owned_but_member_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = self._workspace(root)
            output = io.StringIO()

            with redirect_stdout(output):
                code = main([
                    "graph", str(root), "--native", "--preview", "--json",
                    "--component", "app",
                ])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            yarn = next(plan for plan in data["plans"] if plan["provider"] == "yarn-berry-resolution-graph")
            self.assertEqual(yarn["component"], ".:node")
            self.assertEqual(yarn["selected_component"], "packages/app:node")
            self.assertEqual(yarn["project_root"], ".")
            self.assertEqual(yarn["cwd"], "packages/app")
            self.assertEqual(yarn["commands"], [["yarn", "info", "--recursive", "--virtuals", "--json"]])
            self.assertEqual(yarn["execution_guards"]["network"], "disabled")
            self.assertEqual(yarn["execution_guards"]["install_state"], "temporary")
            self.assertEqual(yarn["execution_guards"]["cache"], "immutable")
            self.assertEqual(yarn["execution_guards"]["telemetry"], "disabled")
            self.assertEqual(yarn["execution_guards"]["hardened_mode"], "unchanged")
            self.assertEqual(data["skips"], [])
            self.assertEqual(member, root / "packages" / "app")

    def test_public_graph_json_returns_yarn_locator_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            graph_plan = plan_yarn_graphs(__import__("unified_project_manager.discovery", fromlist=["discover"]).discover(root))[0]
            packages, edges = parse_yarn_info(_INFO, ".:node")
            result = YarnGraphResult(graph_plan, packages, edges, 0, yarn_version="4.6.0")
            output = io.StringIO()

            with patch(
                "unified_project_manager.graph_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main(["graph", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            yarn = next(item for item in data["results"] if item["provider"] == "yarn-berry-resolution-graph")
            self.assertEqual(yarn["yarn_version"], "4.6.0")
            self.assertIn("app@workspace:packages/app", {item["locator"] for item in yarn["packages"]})
            self.assertIn(
                ("app@workspace:packages/app", "foo@npm:1.2.3"),
                {(edge["source_locator"], edge["target_locator"]) for edge in yarn["edges"]},
            )
            self.assertEqual(data["skips"], [])


if __name__ == "__main__":
    unittest.main()
