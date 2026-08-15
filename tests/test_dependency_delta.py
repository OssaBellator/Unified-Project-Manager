from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.dependency_delta import dependency_delta
from unified_project_manager.discovery import discover


class DependencyDeltaTests(unittest.TestCase):
    def test_direct_requirement_change_is_not_reported_as_remove_plus_add(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text(json.dumps({
                'packageManager': 'npm@11', 'dependencies': {'react': '^18.0.0'}
            }), encoding='utf-8')
            before = discover(root)
            (root / 'package.json').write_text(json.dumps({
                'packageManager': 'npm@11', 'dependencies': {'react': '^19.0.0'}
            }), encoding='utf-8')
            after = discover(root)
            delta = dependency_delta(before, after)
            self.assertEqual(len(delta.direct), 1)
            change = delta.direct[0]
            self.assertEqual(change.status, 'changed')
            self.assertEqual(change.before_requirement, '^18.0.0')
            self.assertEqual(change.after_requirement, '^19.0.0')

    def test_python_names_are_normalized_for_direct_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'requirements.txt').write_text('My_Package==1\n', encoding='utf-8')
            before = discover(root)
            (root / 'requirements.txt').write_text('my-package==2\n', encoding='utf-8')
            after = discover(root)
            delta = dependency_delta(before, after)
            self.assertEqual(len(delta.direct), 1)
            self.assertEqual(delta.direct[0].status, 'changed')

    def test_resolved_version_change_preserves_native_occurrence_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"packageManager":"npm@11"}', encoding='utf-8')
            (root / 'package-lock.json').write_text(json.dumps({
                'lockfileVersion': 3,
                'packages': {'': {}, 'node_modules/foo': {'version': '1.0.0'}},
            }), encoding='utf-8')
            before = discover(root)
            (root / 'package-lock.json').write_text(json.dumps({
                'lockfileVersion': 3,
                'packages': {'': {}, 'node_modules/foo': {'version': '2.0.0'}},
            }), encoding='utf-8')
            after = discover(root)
            delta = dependency_delta(before, after)
            self.assertEqual({item.status for item in delta.resolved}, {'added', 'removed'})
            self.assertEqual({item.version for item in delta.resolved}, {'1.0.0', '2.0.0'})
            self.assertEqual({item.location for item in delta.resolved}, {'node_modules/foo'})

    def test_unchanged_graph_has_empty_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Cargo.toml').write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding='utf-8')
            graph = discover(root)
            delta = dependency_delta(graph, discover(root))
            self.assertFalse(delta.changed)
            self.assertEqual(delta.to_dict()['summary']['direct_changes'], 0)

    def test_different_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = root / 'a'; b = root / 'b'
            a.mkdir(); b.mkdir()
            (a / 'package.json').write_text('{}', encoding='utf-8')
            (b / 'package.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'same project root'):
                dependency_delta(discover(a), discover(b))


if __name__ == '__main__':
    unittest.main()
