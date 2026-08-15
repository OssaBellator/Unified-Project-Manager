from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from unified_project_manager.cargo_cache_provenance import aggregate_cargo_cache_uses, cargo_cache_uses


@dataclass(frozen=True)
class Plan:
    component: str


@dataclass(frozen=True)
class Package:
    package_id: str
    name: str
    version: str
    source: str | None
    manifest_path: str | None


@dataclass
class Result:
    plan: Plan
    packages: list[Package]
    succeeded: bool = True


class CargoCacheProvenanceTests(unittest.TestCase):
    def test_registry_and_git_sources_are_attributed_only_inside_cargo_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cargo_home = root / '.cargo'
            registry = cargo_home / 'registry' / 'src' / 'index' / 'serde-1.0.0'
            git = cargo_home / 'git' / 'checkouts' / 'repo' / 'abc123'
            local = root / 'project' / 'local'
            for directory in (registry, git, local):
                directory.mkdir(parents=True)
            result = Result(Plan('.:rust'), [
                Package('registry+serde#1.0.0', 'serde', '1.0.0', 'registry+https://github.com/rust-lang/crates.io-index', str(registry / 'Cargo.toml')),
                Package('git+foo#abc', 'foo', '0.1.0', 'git+https://example.com/foo', str(git / 'Cargo.toml')),
                Package('path+local#0.1.0', 'local', '0.1.0', None, str(local / 'Cargo.toml')),
            ])
            uses, skipped = cargo_cache_uses(root / 'project', [result], cargo_home)
            self.assertEqual({use.cache_kind for use in uses}, {'registry-source', 'git-checkout'})
            serde = next(use for use in uses if use.name == 'serde')
            self.assertEqual(serde.purl, 'pkg:cargo/serde@1.0.0')
            foo = next(use for use in uses if use.name == 'foo')
            self.assertIsNone(foo.purl)
            self.assertEqual(len(skipped), 1)
            self.assertIn('outside CARGO_HOME', skipped[0]['reason'])

    def test_same_registry_source_directory_groups_across_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cargo_home = root / '.cargo'
            crate = cargo_home / 'registry' / 'src' / 'index' / 'serde-1.0.0'
            crate.mkdir(parents=True)
            (crate / 'lib.rs').write_bytes(b'x' * 12)
            package = Package('registry+serde#1.0.0', 'serde', '1.0.0', 'registry+https://github.com/rust-lang/crates.io-index', str(crate / 'Cargo.toml'))
            one, _ = cargo_cache_uses(root / 'one', [Result(Plan('.:rust'), [package])], cargo_home)
            two, _ = cargo_cache_uses(root / 'two', [Result(Plan('engine:rust'), [package])], cargo_home)
            groups = aggregate_cargo_cache_uses([*one, *two], measure=True)
            self.assertEqual(len(groups), 1)
            group = groups[0]
            self.assertEqual(group.projects, 2)
            self.assertEqual(group.bytes, 12)
            self.assertFalse(group.to_dict()['reclaimable'])

    def test_manifest_outside_cache_is_not_misclassified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cargo_home = root / '.cargo'
            local = root / 'workspace' / 'crate'
            local.mkdir(parents=True)
            package = Package('path+crate#0.1.0', 'crate', '0.1.0', None, str(local / 'Cargo.toml'))
            uses, skipped = cargo_cache_uses(root / 'workspace', [Result(Plan('.:rust'), [package])], cargo_home)
            self.assertEqual(uses, [])
            self.assertEqual(len(skipped), 1)


if __name__ == '__main__':
    unittest.main()
