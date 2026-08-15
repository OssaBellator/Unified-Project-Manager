from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.tasks import (
    TaskError,
    execute_task,
    list_native_tasks,
    load_tasks,
    plan_native_task,
    plan_task,
)


class TaskTests(unittest.TestCase):
    def test_load_and_plan_dependency_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "frontend").mkdir()
            (root / "upm.toml").write_text('''
[tasks.lint]
command = ["python", "-m", "compileall", "src"]

[tasks.test]
command = ["python", "-m", "unittest"]
cwd = "frontend"
depends = ["lint"]
''', encoding="utf-8")
            tasks = load_tasks(root)
            self.assertEqual(tasks["test"].cwd, root / "frontend")
            self.assertEqual([task.name for task in plan_task(root, "test")], ["lint", "test"])

    def test_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('''
[tasks.a]
command = ["python", "a.py"]
depends = ["b"]
[tasks.b]
command = ["python", "b.py"]
depends = ["a"]
''', encoding="utf-8")
            with self.assertRaisesRegex(TaskError, "cycle"):
                plan_task(root, "a")

    def test_cwd_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('''
[tasks.bad]
command = ["python", "x.py"]
cwd = "../outside"
''', encoding="utf-8")
            with self.assertRaisesRegex(TaskError, "escapes"):
                load_tasks(root)

    def test_shell_command_strings_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('[tasks.test]\ncommand = "rm -rf build"\n', encoding="utf-8")
            with self.assertRaisesRegex(TaskError, "array of strings"):
                load_tasks(root)

    def test_execute_task_uses_exact_resolved_argv_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('[tasks.test]\ncommand = ["python", "-m", "unittest"]\n', encoding="utf-8")
            task = plan_task(root, "test")[0]
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "ok\n", "")

            result = execute_task(task, run=fake_run, which=lambda _name: "/bin/python-exact")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["/bin/python-exact", "-m", "unittest"])
            self.assertNotIn("shell", calls[0][1])
            self.assertNotIn("env", calls[0][1])


class NativeTaskTests(unittest.TestCase):
    def test_node_script_uses_authoritative_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = Component(
                "node",
                root / "frontend",
                "pnpm",
                metadata={"scripts": {"test": "vitest"}, "name": "frontend"},
            )
            graph = ProjectGraph(root, [component])
            plan = plan_native_task(graph, "test")
            self.assertEqual(plan.argv, ("pnpm", "run", "test"))
            self.assertEqual(plan.cwd, root / "frontend")

    def test_cargo_core_task_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("rust", root / "engine", "cargo", metadata={"name": "engine"})])
            plan = plan_native_task(graph, "check")
            self.assertEqual(plan.argv, ("cargo", "check"))
            tasks = list_native_tasks(graph)
            self.assertIn("test", {task["name"] for task in tasks})

    def test_go_native_task_is_component_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("go", root / "service", "go", metadata={"name": "example.com/service"})])
            plan = plan_native_task(graph, "test")
            self.assertEqual(plan.argv, ("go", "test", "./..."))
            self.assertEqual(dict(plan.environment), {"GOWORK": "off"})
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "ok\n", "")

            result = execute_task(plan, run=fake_run, which=lambda _name: "/toolchains/go")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["/toolchains/go", "test", "./..."])
            self.assertEqual(calls[0][1]["env"]["GOWORK"], "off")

    def test_ambiguous_native_task_requires_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("node", root / "frontend", "npm", metadata={"scripts": {"test": "vitest"}}),
                Component("rust", root / "engine", "cargo"),
            ])
            with self.assertRaisesRegex(TaskError, "--component"):
                plan_native_task(graph, "test")
            plan = plan_native_task(graph, "test", selector="frontend")
            self.assertEqual(plan.argv, ("npm", "run", "test"))


if __name__ == "__main__":
    unittest.main()
