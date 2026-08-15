from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.tasks import TaskError, execute_task, load_tasks, plan_task


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

    def test_execute_task_uses_argv_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('[tasks.test]\ncommand = ["python", "-m", "unittest"]\n', encoding="utf-8")
            task = plan_task(root, "test")[0]
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "ok\n", "")

            result = execute_task(task, run=fake_run, which=lambda _name: "/bin/python")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["python", "-m", "unittest"])
            self.assertNotIn("shell", calls[0][1])


if __name__ == "__main__":
    unittest.main()
