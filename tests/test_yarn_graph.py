from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.yarn_graph import (
    YarnGraphPlan,
    execute_yarn_graph,
    parse_yarn_info,
    plan_yarn_graphs,
    yarn_provider_component_keys,
)


def _ndjson(records: list[dict]) -> str:
    return "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n"


_YARN_INFO = _ndjson([
    {
        "value": "app@workspace:.",
        "children": {
            "Version": "1.0.0",
            "Dependencies": [
                {"descriptor": "foo@npm:^1.0.0", "locator": "foo@npm:1.2.3"},
                {"descriptor": "peer-user@npm:^2.0.0", "locator": "peer-user@virtual:abc123#npm:2.0.0"},
            ],
        },
    },
    {
        "value": "foo@npm:1.2.3",
        "children": {"Version": "1.2.3"},
    },
    {
        "value": "peer-user@virtual:abc123#npm:2.0.0",
        "children": {
            "Version": "2.0.0",
            "Peer dependencies": [
                {"descriptor": "foo@npm:^1.0.0", "locator": "foo@npm:1.2.3"},
            ],
        },
    },
    {
        "value": "peer-user@npm:2.0.0",
        "children": {
            "Version": "2.0.0",
            "Dependencies": [
                {"descriptor": "foo@npm:^1.0.0", "locator": "foo@npm:1.2.3"},
            ],
        },
    },
])


class YarnGraphTests(unittest.TestCase):
    def _workspace(self, root: Path, version: str = "4.6.0") -> Path:
        (root / "package.json").write_text(json.dumps({
            "name": "root",
            "version": "1.0.0",
            "private": True,
            "packageManager": f"yarn@{version}",
            "workspaces": ["packages/*"],
        }), encoding="utf-8")
        (root / "yarn.lock").write_text("# synthetic test lock\n", encoding="utf-8")
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text(
            '{"name":"app","version":"1.0.0"}', encoding="utf-8"
        )
        return member

    def test_parser_preserves_exact_locators_and_virtual_resolution(self) -> None:
        packages, edges = parse_yarn_info(_YARN_INFO, ".:node")

        by_locator = {package.locator: package for package in packages}
        self.assertTrue(by_locator["app@workspace:."].project_member)
        virtual = by_locator["peer-user@virtual:abc123#npm:2.0.0"]
        self.assertTrue(virtual.virtual)
        self.assertEqual(virtual.protocol, "npm")
        self.assertEqual(virtual.base_locator, "peer-user@npm:2.0.0")
        edge_keys = {
            (edge.source_locator, edge.target_locator, edge.kind)
            for edge in edges
        }
        self.assertIn(("app@workspace:.", "foo@npm:1.2.3", "dependency"), edge_keys)
        self.assertIn((
            "app@workspace:.",
            "peer-user@virtual:abc123#npm:2.0.0",
            "dependency",
        ), edge_keys)
        self.assertIn((
            "peer-user@virtual:abc123#npm:2.0.0",
            "peer-user@npm:2.0.0",
            "devirtualized",
        ), edge_keys)

    def test_workspace_planner_uses_one_root_query_and_member_cwd_for_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = self._workspace(root)
            graph = discover(root)

            all_plans = plan_yarn_graphs(graph)
            selected = plan_yarn_graphs(graph, selector="app")

            self.assertEqual(len(all_plans), 1)
            self.assertEqual(all_plans[0].project_root, root)
            self.assertEqual(all_plans[0].cwd, root)
            self.assertTrue(all_plans[0].all_workspaces)
            self.assertIn("--all", all_plans[0].argv)
            self.assertEqual(
                yarn_provider_component_keys(graph, all_plans),
                {".:node", "packages/app:node"},
            )

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].project_root, root)
            self.assertEqual(selected[0].cwd, member)
            self.assertFalse(selected[0].all_workspaces)
            self.assertNotIn("--all", selected[0].argv)
            self.assertEqual(selected[0].selected_component, "packages/app:node")
            self.assertEqual(
                yarn_provider_component_keys(graph, selected),
                {".:node", "packages/app:node"},
            )

    def test_classic_or_undeclared_yarn_is_not_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            classic = Path(temporary) / "classic"
            classic.mkdir()
            self._workspace(classic, "1.22.22")
            self.assertEqual(plan_yarn_graphs(discover(classic)), [])

            undeclared = Path(temporary) / "undeclared"
            undeclared.mkdir()
            (undeclared / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            (undeclared / "yarn.lock").write_text("# lock\n", encoding="utf-8")
            self.assertEqual(plan_yarn_graphs(discover(undeclared)), [])

    def test_execution_isolates_install_state_disables_network_and_uses_resolved_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            plan = plan_yarn_graphs(discover(root))[0]
            calls: list[tuple[list[str], dict]] = []
            temporary_state: Path | None = None
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

            def run(argv, **kwargs):
                nonlocal temporary_state
                calls.append((list(argv), kwargs))
                if argv[1:] == ["--version"]:
                    return subprocess.CompletedProcess(argv, 0, "4.6.0\n", "")
                env = kwargs["env"]
                temporary_state = Path(env["YARN_INSTALL_STATE_PATH"])
                self.assertFalse(temporary_state.is_relative_to(root))
                self.assertTrue(temporary_state.parent.is_dir())
                self.assertIn(env["YARN_ENABLE_NETWORK"], {"0", "false"})
                self.assertNotIn("YARN_ENABLE_HARDENED_MODE", env)
                self.assertIn(env["YARN_ENABLE_TELEMETRY"], {"0", "false"})
                self.assertIn(env["YARN_ENABLE_IMMUTABLE_CACHE"], {"1", "true"})
                self.assertEqual(argv[0], "/tools/yarn")
                return subprocess.CompletedProcess(argv, 0, _YARN_INFO, "")

            result = execute_yarn_graph(plan, run=run, which=lambda _name: "/tools/yarn")

            self.assertTrue(result.succeeded)
            self.assertEqual(result.yarn_version, "4.6.0")
            self.assertEqual(calls[0][0], ["/tools/yarn", "--version"])
            self.assertEqual(calls[1][0], [
                "/tools/yarn", "info", "--all", "--recursive", "--virtuals", "--json",
            ])
            assert temporary_state is not None
            self.assertFalse(temporary_state.parent.exists())
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(after, before)

    def test_runtime_yarn_classic_is_rejected_before_info_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            plan = YarnGraphPlan(".:node", root, root, True)
            calls = []

            def run(argv, **kwargs):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "1.22.22\n", "")

            result = execute_yarn_graph(plan, run=run, which=lambda _name: "/tools/yarn")

            self.assertFalse(result.succeeded)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(calls, [["/tools/yarn", "--version"]])
            self.assertIn("Berry 2+", result.stderr)


if __name__ == "__main__":
    unittest.main()
