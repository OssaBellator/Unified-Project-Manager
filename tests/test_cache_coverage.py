from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.cache_coverage import summarize_go_cache_attribution
from unified_project_manager.go_cache_provenance import GoCacheGroup, GoCacheUse


class CacheAttributionTests(unittest.TestCase):
    def test_remainder_is_unattributed_not_reclaimable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'modcache'
            referenced = cache / 'example.com' / 'foo@v1.0.0'
            metadata = cache / 'cache' / 'download'
            referenced.mkdir(parents=True); metadata.mkdir(parents=True)
            (referenced / 'foo.go').write_bytes(b'x' * 10)
            (metadata / 'metadata').write_bytes(b'y' * 6)
            use = GoCacheUse(str(root / 'project'), '.:go', 'example.com/foo', 'v1.0.0', 'pkg:golang/example.com/foo@v1.0.0', str(referenced), False)
            group = GoCacheGroup(str(referenced), use.purl, use.module, use.version, 1, 1, None, None, (use,))
            summary = summarize_go_cache_attribution(cache, [group])
            data = summary.to_dict()
            self.assertEqual(summary.total_bytes, 16)
            self.assertEqual(summary.attributed_bytes, 10)
            self.assertEqual(summary.unattributed_bytes, 6)
            self.assertFalse(data['unattributed_means_unused'])
            self.assertIsNone(data['reclaimable_bytes'])
            self.assertFalse(data['coverage_complete'])

    def test_provider_failures_are_retained_as_coverage_limitations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / 'cache'
            cache.mkdir()
            summary = summarize_go_cache_attribution(
                cache,
                [],
                provider_failures=['project A native graph failed'],
                unregistered_projects_possible=False,
            )
            self.assertFalse(summary.coverage_complete)
            self.assertIn('project A native graph failed', summary.limitations)

    def test_complete_flag_requires_no_provider_failures_and_closed_project_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / 'cache'
            cache.mkdir()
            summary = summarize_go_cache_attribution(cache, [], unregistered_projects_possible=False)
            self.assertTrue(summary.coverage_complete)


if __name__ == '__main__':
    unittest.main()
