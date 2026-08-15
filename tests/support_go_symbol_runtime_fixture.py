from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support_go_vulndb_fixture import (
    FIXTURE_MODULE,
    FIXTURE_PACKAGE,
    FIXTURE_SYMBOL,
    write_fixture as write_vulndb_fixture,
)

FIXTURE_VERSION = "v1.2.3"
FIXTURE_GO_VERSION = "1.23"
FIXTURE_TIME = "2026-01-01T00:00:00Z"
FIXTURE_APP_MODULE = "example.com/app"


@dataclass(frozen=True)
class GoSymbolRuntimeFixture:
    root: Path
    project: Path
    proxy: Path
    vulnerability_db: Path
    module_cache: Path
    build_cache: Path

    @property
    def proxy_uri(self) -> str:
        return self.proxy.resolve().as_uri()

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root.resolve()),
            "project": str(self.project.resolve()),
            "proxy": str(self.proxy.resolve()),
            "proxy_uri": self.proxy_uri,
            "vulnerability_db": str(self.vulnerability_db.resolve()),
            "module_cache": str(self.module_cache.resolve()),
            "build_cache": str(self.build_cache.resolve()),
            "module": FIXTURE_MODULE,
            "version": FIXTURE_VERSION,
            "package": FIXTURE_PACKAGE,
            "symbol": FIXTURE_SYMBOL,
        }


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def _write_module_proxy(proxy: Path) -> None:
    version_dir = proxy / FIXTURE_MODULE / "@v"
    version_dir.mkdir(parents=True, exist_ok=True)
    module_text = f"module {FIXTURE_MODULE}\n\ngo {FIXTURE_GO_VERSION}\n"
    source_text = (
        "package pkg\n\n"
        "func Danger() string { return \"synthetic vulnerable symbol\" }\n"
        "func Safe() string { return \"safe\" }\n"
    )

    _write_text(version_dir / "list", FIXTURE_VERSION + "\n")
    _write_text(
        version_dir / f"{FIXTURE_VERSION}.info",
        json.dumps({"Version": FIXTURE_VERSION, "Time": FIXTURE_TIME}, sort_keys=True) + "\n",
    )
    _write_text(version_dir / f"{FIXTURE_VERSION}.mod", module_text)

    zip_path = version_dir / f"{FIXTURE_VERSION}.zip"
    prefix = f"{FIXTURE_MODULE}@{FIXTURE_VERSION}/"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(_zip_info(prefix + "go.mod"), module_text)
        archive.writestr(_zip_info(prefix + "pkg/dep.go"), source_text)


def _write_project(project: Path) -> None:
    _write_text(
        project / "go.mod",
        f"module {FIXTURE_APP_MODULE}\n\n"
        f"go {FIXTURE_GO_VERSION}\n\n"
        f"require {FIXTURE_MODULE} {FIXTURE_VERSION}\n",
    )
    _write_text(
        project / "main.go",
        "package main\n\n"
        f'import dep "{FIXTURE_PACKAGE}"\n\n'
        "func main() { _ = dep.Danger() }\n",
    )


def write_runtime_fixture(root: str | Path) -> GoSymbolRuntimeFixture:
    target = Path(root).expanduser().resolve()
    project = target / "project"
    proxy = target / "proxy"
    vulnerability_db = target / "vulndb"
    module_cache = target / "gomodcache"
    build_cache = target / "gocache"

    project.mkdir(parents=True, exist_ok=True)
    module_cache.mkdir(parents=True, exist_ok=True)
    build_cache.mkdir(parents=True, exist_ok=True)
    _write_project(project)
    _write_module_proxy(proxy)
    write_vulndb_fixture(vulnerability_db)
    return GoSymbolRuntimeFixture(
        target, project, proxy, vulnerability_db, module_cache, build_cache
    )


def fixture_go_environment(fixture: GoSymbolRuntimeFixture) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "GOMODCACHE": str(fixture.module_cache),
        "GOCACHE": str(fixture.build_cache),
        "GOWORK": "off",
        "GOSUMDB": "off",
        "GOTOOLCHAIN": "local",
    })
    return env


def prepare_module_cache(
    fixture: GoSymbolRuntimeFixture,
    *,
    go_executable: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Populate the isolated module cache from the local file proxy only."""

    executable = go_executable or shutil.which("go")
    if not executable:
        raise FileNotFoundError("Go executable is not available")
    env = fixture_go_environment(fixture)
    env["GOPROXY"] = fixture.proxy_uri
    return subprocess.run(
        [executable, "mod", "download", "-json", f"{FIXTURE_MODULE}@{FIXTURE_VERSION}"],
        cwd=fixture.project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def verify_offline_module_available(
    fixture: GoSymbolRuntimeFixture,
    *,
    go_executable: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Verify the populated versioned dependency works with GOPROXY=off."""

    executable = go_executable or shutil.which("go")
    if not executable:
        raise FileNotFoundError("Go executable is not available")
    env = fixture_go_environment(fixture)
    env["GOPROXY"] = "off"
    return subprocess.run(
        [executable, "list", "-mod=readonly", "-deps", "./..."],
        cwd=fixture.project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Create UPM's fully local Go symbol-runtime validation fixture"
    )
    parser.add_argument("destination")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    fixture = write_runtime_fixture(args.destination)
    if args.prepare:
        completed = prepare_module_cache(fixture)
        if completed.returncode != 0:
            raise SystemExit(completed.stderr or completed.stdout or completed.returncode)
    if args.as_json:
        print(json.dumps(fixture.to_dict(), indent=2, sort_keys=True))
    else:
        print(fixture.project)
