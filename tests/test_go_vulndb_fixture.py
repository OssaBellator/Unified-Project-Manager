from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from support_go_vulndb_fixture import (
    FIXTURE_ALIAS,
    FIXTURE_FIXED,
    FIXTURE_ID,
    FIXTURE_MODIFIED,
    FIXTURE_MODULE,
    FIXTURE_PACKAGE,
    FIXTURE_SYMBOL,
    OSV_SCHEMA_VERSION,
    write_fixture,
)


class GoVulnDbFixtureTests(unittest.TestCase):
    def _json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _file_digests(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_writes_exact_v1_files_and_no_extra_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "db"
            fixture = write_fixture(root)

            self.assertEqual(fixture.root, root.resolve())
            self.assertEqual(fixture.uri, root.resolve().as_uri())
            self.assertEqual(
                set(self._file_digests(root)),
                {
                    "ID/GO-2099-0001.json",
                    "index/db.json",
                    "index/modules.json",
                    "index/vulns.json",
                },
            )

    def test_modules_index_matches_v1_array_shape_and_bare_fixed_semver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "db"
            write_fixture(root)
            modules = self._json(root / "index" / "modules.json")

            self.assertIsInstance(modules, list)
            self.assertEqual(modules, [{
                "path": FIXTURE_MODULE,
                "vulns": [{
                    "fixed": FIXTURE_FIXED,
                    "id": FIXTURE_ID,
                    "modified": FIXTURE_MODIFIED,
                }],
            }])
            self.assertFalse(FIXTURE_FIXED.startswith("v"))

    def test_vulns_and_db_indexes_share_exact_identity_and_modified_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "db"
            write_fixture(root)
            db = self._json(root / "index" / "db.json")
            vulns = self._json(root / "index" / "vulns.json")

            self.assertEqual(db, {"modified": FIXTURE_MODIFIED})
            self.assertEqual(vulns, [{
                "aliases": [FIXTURE_ALIAS],
                "id": FIXTURE_ID,
                "modified": FIXTURE_MODIFIED,
            }])

    def test_osv_entry_is_symbol_scoped_go_semver_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "db"
            write_fixture(root)
            entry = self._json(root / "ID" / f"{FIXTURE_ID}.json")

            self.assertEqual(entry["schema_version"], OSV_SCHEMA_VERSION)
            self.assertEqual(entry["id"], FIXTURE_ID)
            self.assertEqual(entry["aliases"], [FIXTURE_ALIAS])
            self.assertEqual(entry["modified"], FIXTURE_MODIFIED)
            self.assertEqual(entry["published"], FIXTURE_MODIFIED)
            self.assertEqual(len(entry["affected"]), 1)
            affected = entry["affected"][0]
            self.assertEqual(affected["package"], {
                "name": FIXTURE_MODULE,
                "ecosystem": "Go",
            })
            self.assertEqual(affected["ranges"], [{
                "type": "SEMVER",
                "events": [
                    {"introduced": "0"},
                    {"fixed": FIXTURE_FIXED},
                ],
            }])
            self.assertEqual(affected["ecosystem_specific"], {
                "imports": [{
                    "path": FIXTURE_PACKAGE,
                    "symbols": [FIXTURE_SYMBOL],
                }],
            })

    def test_fixture_metadata_matches_written_osv_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "db"
            fixture = write_fixture(root)
            entry = self._json(root / "ID" / f"{fixture.vuln_id}.json")
            module = self._json(root / "index" / "modules.json")[0]

            self.assertEqual(fixture.vuln_id, entry["id"])
            self.assertEqual(fixture.alias, entry["aliases"][0])
            self.assertEqual(fixture.module, module["path"])
            package = entry["affected"][0]["ecosystem_specific"]["imports"][0]
            self.assertEqual(fixture.package, package["path"])
            self.assertEqual(fixture.symbol, package["symbols"][0])
            self.assertEqual(fixture.fixed, module["vulns"][0]["fixed"])

    def test_repeated_generation_is_byte_for_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            one = base / "one"
            two = base / "two"
            write_fixture(one)
            write_fixture(two)
            self.assertEqual(self._file_digests(one), self._file_digests(two))

    def test_rewrite_replaces_endpoint_content_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "db"
            write_fixture(root)
            target = root / "index" / "modules.json"
            target.write_text('[{"path":"corrupted","vulns":[]}]\n', encoding="utf-8")

            write_fixture(root)
            modules = self._json(target)
            self.assertEqual(modules[0]["path"], FIXTURE_MODULE)
            self.assertEqual(len(modules[0]["vulns"]), 1)


if __name__ == "__main__":
    unittest.main()
