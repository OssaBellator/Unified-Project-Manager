from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.entrypoint import main


class EntrypointTests(unittest.TestCase):
    def _node_project(self, root: Path) -> None:
        (root / "package.json").write_text(json.dumps({
            "packageManager": "pnpm@10",
            "scripts": {"test": "vitest", "dev": "vite"},
        }), encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    def test_native_task_preview_uses_native_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["run", "test", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("pnpm run test", output.getvalue())
            self.assertIn("Preview only", output.getvalue())

    def test_upm_task_takes_precedence_over_native_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            (root / "upm.toml").write_text('[tasks.test]\ncommand = ["python", "-m", "unittest"]\n', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["run", "test", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("python -m unittest", output.getvalue())
            self.assertNotIn("pnpm run test", output.getvalue())

    def test_tasks_json_lists_configured_and_native(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            (root / "upm.toml").write_text('[tasks.lint]\ncommand = ["python", "-m", "compileall", "src"]\n', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["tasks", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual({row["source"] for row in data["tasks"]}, {"upm", "native"})

    def test_storage_json_measures_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._node_project(root)
            module = root / "node_modules" / "x"
            module.mkdir(parents=True)
            (module / "data.bin").write_bytes(b"x" * 32)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["storage", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["bytes"], 32)
            self.assertEqual(data["entries"][0]["path"], "node_modules")


if __name__ == "__main__":
    unittest.main()
