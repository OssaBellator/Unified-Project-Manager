from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from unified_project_manager.go_cache_provenance import aggregate_go_cache_uses, go_cache_uses


@dataclass(frozen=True)
class Plan:
    component: str


@dataclass(frozen=True)
class Module:
    effective_name: str
    effective_version: str | None
    directory: str | None
    main: bool = False
    replacement_name: str | None = None
    replacement_version: str | None = None
    replacement_dir: str | None = None


@dataclass
class Result:
    plan: Plan
    modules: list[Module]
    succeeded: bool = True


class GoCacheProvenanceTests(unittest.TestCase):
    def test_maps_only_native_module_directories_under_modcache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'gomodcache'
            cached = cache / 'example.com' / 'foo@v1.2.3'
            local = root / 'local'
            cached.mkdir(parents=True); local.mkdir()
            result = Result(Plan('.:go'), [
                Module('example.com/foo', 'v1.2.3', str(cached)),
                Module('example.com/local', 'v0.1.0', str(local)),
            ])
            uses, skipped = go_cache_uses(root / 'project', [result], cache)
            self.assertEqual(len(uses), 1)
            self.assertEqual(uses[0].purl, 'pkg:golang/example.com/foo@v1.2.3')
            self.assertEqual(skipped[0]['reason'], 'selected module directory is outside GOMODCACHE')

    def test_same_physical_module_directory_groups_across_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'cache'
            module_dir = cache / 'foo@v1.0.0'
            module_dir.mkdir(parents=True)
            (module_dir / 'file.go').write_bytes(b'x' * 10)
            one = Result(Plan('.:go'), [Module('example.com/foo', 'v1.0.0', str(module_dir))])
            two = Result(Plan('service:go'), [Module('example.com/foo', 'v1.0.0', str(module_dir))])
            uses_one, _ = go_cache_uses(root / 'one', [one], cache)
            uses_two, _ = go_cache_uses(root / 'two', [two], cache)
            groups = aggregate_go_cache_uses([*uses_one, *uses_two], measure=True)
            self.assertEqual(len(groups), 1)
            group = groups[0]
            self.assertEqual(group.projects, 2)
            self.assertEqual(group.bytes, 10)
            data = group.to_dict()
            self.assertTrue(data['shared_across_projects'])
            self.assertFalse(data['reclaimable'])

    def test_versioned_replacement_uses_replacement_directory_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'cache'
            replacement = cache / 'new@v2.0.0'
            replacement.mkdir(parents=True)
            module = Module(
                'example.com/new', 'v2.0.0', None,
                replacement_name='example.com/new', replacement_version='v2.0.0', replacement_dir=str(replacement),
            )
            uses, skipped = go_cache_uses(root / 'project', [Result(Plan('.:go'), [module])], cache)
            self.assertEqual(skipped, [])
            self.assertTrue(uses[0].replacement)
            self.assertEqual(uses[0].path, str(replacement.resolve()))


if __name__ == '__main__':
    unittest.main()
