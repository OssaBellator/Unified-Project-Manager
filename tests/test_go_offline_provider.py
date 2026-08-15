from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.go_offline_provider import execute_native_graph_offline, query_native_why_offline
from unified_project_manager.native_graph import plan_native_graph


class GoOfflineProviderTests(unittest.TestCase):
    def test_graph_wrapper_forces_goproxy_off_and_preserves_go_work_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'go.mod').write_text('module example.com/app\ngo 1.24\n', encoding='utf-8')
            plan = plan_native_graph(discover(root))[0][0]
            calls = []

            selected = '{"Path":"example.com/app","Main":true}\n{"Path":"example.com/foo","Version":"v1.0.0"}\n'
            graph = 'example.com/app example.com/foo@v1.0.0\n'

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                if 'list' in argv:
                    return subprocess.CompletedProcess(argv, 0, selected, '')
                return subprocess.CompletedProcess(argv, 0, graph, '')

            result = execute_native_graph_offline(plan, run=run, which=lambda _name: '/tools/go')
            self.assertTrue(result.succeeded)
            self.assertEqual(len(calls), 2)
            for _argv, kwargs in calls:
                self.assertEqual(kwargs['env']['GOPROXY'], 'off')

    def test_why_wrapper_forces_goproxy_off(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'go.mod').write_text('module example.com/app\ngo 1.24\n', encoding='utf-8')
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, '# example.com/foo\nexample.com/app/pkg\nexample.com/foo/pkg\n', '')

            results, skips = query_native_why_offline(discover(root), 'example.com/foo', run=run, which=lambda _name: '/tools/go')
            self.assertEqual(skips, [])
            self.assertTrue(results[0].needed)
            self.assertEqual(calls[0][1]['env']['GOPROXY'], 'off')

    def test_existing_environment_is_preserved_except_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'go.mod').write_text('module example.com/app\ngo 1.24\n', encoding='utf-8')
            plan = plan_native_graph(discover(root))[0][0]
            observed = []

            def run(argv, **kwargs):
                observed.append(kwargs['env'])
                output = '{"Path":"example.com/app","Main":true}\n' if 'list' in argv else ''
                return subprocess.CompletedProcess(argv, 0, output, '')

            old = os.environ.get('UPM_TEST_SENTINEL')
            os.environ['UPM_TEST_SENTINEL'] = 'present'
            try:
                execute_native_graph_offline(plan, run=run, which=lambda _name: '/tools/go')
            finally:
                if old is None:
                    os.environ.pop('UPM_TEST_SENTINEL', None)
                else:
                    os.environ['UPM_TEST_SENTINEL'] = old
            self.assertEqual(observed[0]['UPM_TEST_SENTINEL'], 'present')
            self.assertEqual(observed[0]['GOPROXY'], 'off')


if __name__ == '__main__':
    unittest.main()
