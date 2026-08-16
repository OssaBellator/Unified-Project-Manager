from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any], code: int) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


def _run(argv: list[str], *, cwd: Path | None = None, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _go_minor(version_text: str) -> int | None:
    match = re.search(r"\bgo1\.(\d+)(?:\D|$)", version_text)
    return int(match.group(1)) if match else None


def _go_env(go: str, key: str, *, env: dict[str, str]) -> tuple[str | None, str | None]:
    result = _run([go, "env", key], env=env)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return None, f"`go env {key}` failed with exit {result.returncode}: {detail}"
    return (result.stdout or "").strip(), None


def _selected_files(go: str, project: Path, *, env: dict[str, str]) -> tuple[set[str] | None, set[str] | None, str | None]:
    result = _run([go, "list", "-mod=readonly", "-json", "."], cwd=project, env=env)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return None, None, f"`go list -json .` failed with exit {result.returncode}: {detail}"
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        return None, None, f"`go list -json .` returned invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, None, "`go list -json .` returned a non-object"
    go_files = payload.get("GoFiles", [])
    ignored = payload.get("IgnoredGoFiles", [])
    if not isinstance(go_files, list) or not all(isinstance(item, str) for item in go_files):
        return None, None, "`go list` GoFiles is malformed"
    if not isinstance(ignored, list) or not all(isinstance(item, str) for item in ignored):
        return None, None, "`go list` IgnoredGoFiles is malformed"
    return set(go_files), set(ignored), None


def main() -> int:
    go = shutil.which("go")
    if go is None:
        return _emit({
            "status": "blocked",
            "reasons": ["Go executable is not available"],
            "interpretation": "GOENV normalization characterization did not run; blocked is not a pass.",
        }, 2)

    version_result = _run([go, "version"], env=dict(os.environ))
    version_text = (version_result.stdout or version_result.stderr or "").strip()
    minor = _go_minor(version_text)
    if version_result.returncode != 0 or minor is None or minor < 21:
        return _emit({
            "status": "blocked",
            "go": go,
            "go_version_output": version_text,
            "reasons": ["Go 1.21+ is required for the candidate source-observation profile"],
            "interpretation": "GOENV normalization characterization did not run; blocked is not a pass.",
        }, 2)

    with tempfile.TemporaryDirectory(prefix="upm-goenv-") as temporary:
        root = Path(temporary)
        project = root / "app"
        project.mkdir()
        (project / "go.mod").write_text("module example.com/goenvprobe\n\ngo 1.21\n", encoding="utf-8")
        (project / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
        (project / "ambient.go").write_text(
            "//go:build ambient\n\npackage main\n\nvar Ambient = true\n",
            encoding="utf-8",
        )

        goenv_file = root / "goenv"
        base = dict(os.environ)
        for key in ("GOFLAGS", "GOENV"):
            base.pop(key, None)
        base.update({
            "GOPROXY": "off",
            "GOWORK": "off",
            "GOSUMDB": "off",
            "GOTOOLCHAIN": "local",
        })

        persisted_env = dict(base)
        persisted_env["GOENV"] = str(goenv_file)
        write_result = _run([go, "env", "-w", "GOFLAGS=-tags=ambient"], env=persisted_env)
        if write_result.returncode != 0:
            detail = (write_result.stderr or write_result.stdout or "").strip()
            return _emit({
                "status": "failed",
                "go": go,
                "go_version_output": version_text,
                "reasons": [f"isolated `go env -w` failed with exit {write_result.returncode}: {detail}"],
                "isolated_goenv": str(goenv_file),
                "user_goenv_mutated": False,
            }, 1)

        off_env = dict(base)
        off_env.update({"GOENV": "off", "GOFLAGS": ""})
        process_env = dict(base)
        process_env.update({"GOENV": "off", "GOFLAGS": "-tags=ambient"})

        persisted_flags, error = _go_env(go, "GOFLAGS", env=persisted_env)
        if error:
            return _emit({"status": "failed", "reasons": [error]}, 1)
        off_flags, error = _go_env(go, "GOFLAGS", env=off_env)
        if error:
            return _emit({"status": "failed", "reasons": [error]}, 1)
        process_flags, error = _go_env(go, "GOFLAGS", env=process_env)
        if error:
            return _emit({"status": "failed", "reasons": [error]}, 1)

        persisted_files, persisted_ignored, error = _selected_files(go, project, env=persisted_env)
        if error:
            return _emit({"status": "failed", "reasons": [error]}, 1)
        off_files, off_ignored, error = _selected_files(go, project, env=off_env)
        if error:
            return _emit({"status": "failed", "reasons": [error]}, 1)
        process_files, process_ignored, error = _selected_files(go, project, env=process_env)
        if error:
            return _emit({"status": "failed", "reasons": [error]}, 1)

        checks = {
            "persisted_goflags_loaded": persisted_flags == "-tags=ambient",
            "goenv_off_clears_persisted_goflags": off_flags == "",
            "process_goflags_survives_goenv_off": process_flags == "-tags=ambient",
            "persisted_goflags_selects_ambient_file": "ambient.go" in (persisted_files or set()),
            "goenv_off_ignores_ambient_file": (
                "ambient.go" not in (off_files or set())
                and "ambient.go" in (off_ignored or set())
            ),
            "process_goflags_selects_ambient_file_with_goenv_off": "ambient.go" in (process_files or set()),
        }
        failures = [name for name, passed in checks.items() if not passed]
        status = "ok" if not failures else "failed"
        return _emit({
            "status": status,
            "go": go,
            "go_version_output": version_text,
            "isolated_goenv": str(goenv_file),
            "user_goenv_mutated": False,
            "checks": checks,
            "observed": {
                "persisted_goflags": persisted_flags,
                "goenv_off_goflags": off_flags,
                "process_goflags_with_goenv_off": process_flags,
                "persisted_go_files": sorted(persisted_files or set()),
                "persisted_ignored_go_files": sorted(persisted_ignored or set()),
                "goenv_off_go_files": sorted(off_files or set()),
                "goenv_off_ignored_go_files": sorted(off_ignored or set()),
                "process_go_files_with_goenv_off": sorted(process_files or set()),
                "process_ignored_go_files_with_goenv_off": sorted(process_ignored or set()),
            },
            "reasons": failures,
            "interpretation": (
                "This characterizes Go-command GOENV/GOFLAGS behavior only. It supports GOENV=off as a "
                "candidate normalization for disabling persisted `go env -w` state while preserving explicit "
                "process GOFLAGS. It does not establish govulncheck source/build equivalence or freshness."
            ),
        }, 0 if not failures else 1)


if __name__ == "__main__":
    raise SystemExit(main())
