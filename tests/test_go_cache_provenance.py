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
            self.assertEqual(uses[0].cache_kind, 'module-source')
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
            self.assertEqual(group.cache_kind, 'module-source')
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

    def test_selected_module_reuses_native_encoded_path_for_existing_download_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'gomodcache'
            # The physical path deliberately contains Go's uppercase escape.
            # UPM must reuse this native-reported spelling rather than trying to
            # derive it from the logical module name itself.
            module_dir = cache / 'example.com' / '!foo@v1.2.3'
            module_dir.mkdir(parents=True)
            download = cache / 'cache' / 'download' / 'example.com' / '!foo' / '@v'
            download.mkdir(parents=True)
            sizes = {'info': 2, 'mod': 3, 'zip': 5, 'ziphash': 7}
            for suffix, size in sizes.items():
                (download / f'v1.2.3.{suffix}').write_bytes(b'x' * size)
            # Operational/other-version files are not attributed to this
            # selected module occurrence.
            (download / 'v1.2.3.lock').write_bytes(b'x' * 11)
            (download / 'v9.9.9.zip').write_bytes(b'x' * 13)

            uses, skipped = go_cache_uses(
                root / 'project',
                [Result(Plan('.:go'), [Module('example.com/Foo', 'v1.2.3', str(module_dir))])],
                cache,
            )

            self.assertEqual(skipped, [])
            by_kind = {use.cache_kind: use for use in uses}
            self.assertEqual(set(by_kind), {
                'module-source', 'download-info', 'download-mod', 'download-zip', 'download-ziphash',
            })
            self.assertEqual(by_kind['module-source'].purl, 'pkg:golang/example.com/Foo@v1.2.3')
            for suffix in sizes:
                self.assertEqual(
                    Path(by_kind[f'download-{suffix}'].path),
                    (download / f'v1.2.3.{suffix}').resolve(),
                )

            groups = aggregate_go_cache_uses(uses, measure=True)
            measured = {group.cache_kind: group.bytes for group in groups}
            self.assertEqual(measured['module-source'], 0)
            for suffix, size in sizes.items():
                self.assertEqual(measured[f'download-{suffix}'], size)
            self.assertTrue(all(not group.to_dict()['reclaimable'] for group in groups))

    def test_noncanonical_native_directory_does_not_guess_download_cache_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'gomodcache'
            module_dir = cache / 'example.com' / 'foo'
            module_dir.mkdir(parents=True)
            crafted = cache / 'cache' / 'download' / 'example.com' / 'foo' / '@v'
            crafted.mkdir(parents=True)
            (crafted / 'v1.2.3.zip').write_bytes(b'zip')

            uses, skipped = go_cache_uses(
                root / 'project',
                [Result(Plan('.:go'), [Module('example.com/foo', 'v1.2.3', str(module_dir))])],
                cache,
            )

            self.assertEqual(skipped, [])
            self.assertEqual(len(uses), 1)
            self.assertEqual(uses[0].cache_kind, 'module-source')


if __name__ == '__main__':
    unittest.main()
