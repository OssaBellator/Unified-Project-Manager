from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIXTURE_ID = "GO-2099-0001"
FIXTURE_ALIAS = "CVE-2099-0001"
FIXTURE_MODULE = "example.com/dep"
FIXTURE_PACKAGE = "example.com/dep/pkg"
FIXTURE_SYMBOL = "Danger"
FIXTURE_FIXED = "1.2.4"
FIXTURE_MODIFIED = "2099-01-01T00:00:00Z"
FIXTURE_PUBLISHED = "2099-01-01T00:00:00Z"
OSV_SCHEMA_VERSION = "1.3.1"


@dataclass(frozen=True)
class GoVulnDbFixture:
    root: Path
    vuln_id: str
    alias: str
    module: str
    package: str
    symbol: str
    fixed: str

    @property
    def uri(self) -> str:
        return self.root.resolve().as_uri()

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root.resolve()),
            "uri": self.uri,
            "vuln_id": self.vuln_id,
            "alias": self.alias,
            "module": self.module,
            "package": self.package,
            "symbol": self.symbol,
            "fixed": self.fixed,
        }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_fixture(root: str | Path) -> GoVulnDbFixture:
    """Write one deterministic Go vulnerability database v1 filesystem fixture.

    The fixture uses only the published v1 database endpoints consumed by the
    Go vulnerability client: index/db.json, index/modules.json,
    index/vulns.json, and ID/<GO-ID>.json. It does not import x/vulndb internal
    packages or rely on the vulnerability team's repository/report format.
    """

    target = Path(root).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    db_meta = {"modified": FIXTURE_MODIFIED}
    modules = [
        {
            "path": FIXTURE_MODULE,
            "vulns": [
                {
                    "id": FIXTURE_ID,
                    "modified": FIXTURE_MODIFIED,
                    "fixed": FIXTURE_FIXED,
                }
            ],
        }
    ]
    vulns = [
        {
            "id": FIXTURE_ID,
            "modified": FIXTURE_MODIFIED,
            "aliases": [FIXTURE_ALIAS],
        }
    ]
    entry = {
        "schema_version": OSV_SCHEMA_VERSION,
        "id": FIXTURE_ID,
        "modified": FIXTURE_MODIFIED,
        "published": FIXTURE_PUBLISHED,
        "aliases": [FIXTURE_ALIAS],
        "summary": "UPM deterministic local symbol-reachability fixture",
        "details": (
            "Synthetic local-only validation record for UPM's govulncheck "
            "symbol-reachability boundary."
        ),
        "affected": [
            {
                "package": {
                    "name": FIXTURE_MODULE,
                    "ecosystem": "Go",
                },
                "ranges": [
                    {
                        "type": "SEMVER",
                        "events": [
                            {"introduced": "0"},
                            {"fixed": FIXTURE_FIXED},
                        ],
                    }
                ],
                "ecosystem_specific": {
                    "imports": [
                        {
                            "path": FIXTURE_PACKAGE,
                            "symbols": [FIXTURE_SYMBOL],
                        }
                    ]
                },
            }
        ],
    }

    _write_json(target / "index" / "db.json", db_meta)
    _write_json(target / "index" / "modules.json", modules)
    _write_json(target / "index" / "vulns.json", vulns)
    _write_json(target / "ID" / f"{FIXTURE_ID}.json", entry)

    return GoVulnDbFixture(
        root=target,
        vuln_id=FIXTURE_ID,
        alias=FIXTURE_ALIAS,
        module=FIXTURE_MODULE,
        package=FIXTURE_PACKAGE,
        symbol=FIXTURE_SYMBOL,
        fixed=FIXTURE_FIXED,
    )


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Create UPM's deterministic local Go vulnerability DB v1 fixture"
    )
    parser.add_argument("destination")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    fixture = write_fixture(args.destination)
    if args.as_json:
        print(json.dumps(fixture.to_dict(), indent=2, sort_keys=True))
    else:
        print(fixture.uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
