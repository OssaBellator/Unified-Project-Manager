from __future__ import annotations

import unittest

from unified_project_manager.python_lock_render import render_python_lock_query


class PythonLockRenderTests(unittest.TestCase):
    def test_possible_only_query_renders_ambiguity_path_and_conditions(self) -> None:
        payload = {
            "possible_packages": [{
                "name": "leaf",
                "version": "3.0.0",
                "possible": True,
                "paths_truncated": False,
                "paths": [{
                    "nodes": ["project:.:python", "parent@1.0.0", "?shared", "shared@1.0.0", "leaf@3.0.0"],
                    "markers": ["sys_platform == 'linux'"],
                    "optional_edges": 1,
                }],
            }],
            "ambiguities": [],
            "search_truncated": False,
        }

        rendered = "\n".join(render_python_lock_query(payload))

        self.assertIn("leaf@3.0.0 [possible via ambiguous lock reference]", rendered)
        self.assertIn("?shared", rendered)
        self.assertIn("sys_platform == 'linux'", rendered)
        self.assertIn("optional edges: 1", rendered)

    def test_truncation_is_visible(self) -> None:
        payload = {
            "packages": [],
            "possible_packages": [{
                "name": "leaf",
                "version": "3.0.0",
                "paths_truncated": True,
                "paths": [],
            }],
            "ambiguities": [],
            "search_truncated": True,
        }

        rendered = "\n".join(render_python_lock_query(payload))

        self.assertIn("additional possible paths were truncated", rendered)
        self.assertIn("search state budget was reached", rendered)


if __name__ == "__main__":
    unittest.main()
