from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
                {"descriptor":"git-dep@git:https://example.invalid/x.git","locator":"git-dep@git:https://example.invalid/x.git#commit=abc"},
            ],
        },
    }),
    json.dumps({"value":"foo@npm:1.2.3","children":{"Version":"1.2.3"}}),
    json.dumps({"value":"git-dep@git:https://example.invalid/x.git#commit=abc","children":{"Version":"9.9.9"}}),
]) + "\n"


class YarnSbomEntrypointTests(unittest.TestCase):
    def _fixture(self, root: Path) -> YarnGraphResult:
        (root / "package.json").write_text(json.dumps({
            "name":"root","version":"1.0.0","private":True,
            "packageManager":"yarn@4.6.0","workspaces":["packages/*"],
        }), encoding="utf-8")
        (root / "yarn.lock").write_text("# lock\n", encoding="utf-8")
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"name":"app","version":"1.0.0"}', encoding="utf-8")
        graph = discover(root)
        plan = plan_yarn_graphs(graph, selector="app")[0]
        packages, edges = parse_yarn_info(_INFO, plan.component)
        return YarnGraphResult(plan, packages, edges, 0, yarn_version="4.6.0")

    def test_selected_member_cyclonedx_uses_only_npm_backed_yarn_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._fixture(root)
            output = io.StringIO()

            with patch(
                "unified_project_manager.sbom_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main([
                    "sbom", str(root), "--native", "--component", "app",
                ])
            document = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            purls = {item.get("purl") for item in document.get("components", []) if item.get("purl")}
            self.assertEqual(purls, {"pkg:npm/foo@1.2.3"})
            self.assertNotIn("git-dep", json.dumps(document))
            foo = next(item for item in document["components"] if item.get("purl") == "pkg:npm/foo@1.2.3")
            self.assertIn(
                {"name":"upm:yarn:scope-component","value":"packages/app:node"},
                foo.get("properties", []),
            )

    def test_selected_member_spdx_uses_same_yarn_registry_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._fixture(root)
            output = io.StringIO()

            with patch(
                "unified_project_manager.sbom_provider_entrypoint.execute_yarn_graph",
                return_value=result,
            ), redirect_stdout(output):
                code = main([
                    "sbom", str(root), "--native", "--component", "app",
                    "--format", "spdx",
                ])
            document = json.loads(output.getvalue())

            self.assertEqual(code, 0)
            purls = {
                ref["referenceLocator"]
                for package in document.get("packages", [])
                for ref in package.get("externalRefs", [])
                if ref.get("referenceType") == "purl"
            }
            self.assertEqual(purls, {"pkg:npm/foo@1.2.3"})
            self.assertNotIn("git-dep", json.dumps(document))

    def test_native_sbom_fails_closed_when_yarn_provider_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._fixture(root)
            failed = YarnGraphResult(
                result.plan, [], [], 1, yarn_version="4.6.0", stderr="lock resolution unavailable offline"
            )
            stdout = io.StringIO(); stderr = io.StringIO()

            with patch(
                "unified_project_manager.sbom_provider_entrypoint.execute_yarn_graph",
                return_value=failed,
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["sbom", str(root), "--native", "--component", "app"])

            self.assertEqual(code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("lock resolution unavailable offline", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
