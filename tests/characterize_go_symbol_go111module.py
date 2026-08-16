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


def _run(
    argv: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
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


def main() -> int:
    go = shutil.which("go")
    if go is None:
        return _emit({
            "status": "blocked",
            "reasons": ["Go executable is not available"],
            "interpretation": "GO111MODULE characterization did not run; blocked is not a pass.",
        }, 2)

    version = _run([go, "version"], cwd=None, env=dict(os.environ))
    version_text = (version.stdout or version.stderr or "").strip()
    minor = _go_minor(version_text)
    if version.returncode != 0 or minor is None or minor < 21:
        return _emit({
            "status": "blocked",
            "go": go,
            "go_version_output": version_text,
            "reasons": ["Go 1.21+ is required for the candidate source-observation profile"],
            "interpretation": "GO111MODULE characterization did not run; blocked is not a pass.",
        }, 2)

    with tempfile.TemporaryDirectory(prefix="upm-go111module-") as temporary:
        project = Path(temporary) / "app"
        project.mkdir()
        (project / "go.mod").write_text(
            "module example.com/go111probe\n\ngo 1.21\n",
            encoding="utf-8",
        )
        (project / "main.go").write_text(
            "package main\n\nfunc main() {}\n",
            encoding="utf-8",
        )

        base = dict(os.environ)
        for key in ("GO111MODULE", "GOFLAGS", "GOROOT"):
            base.pop(key, None)
        base.update({
            "GOPROXY": "off",
            "GOWORK": "off",
            "GOSUMDB": "off",
            "GOTOOLCHAIN": "local",
            "GOENV": "off",
            "GOFLAGS": "",
            "GOROOT": "",
        })

        observed: dict[str, dict[str, Any]] = {}
        for label, value in (
            ("unset", None),
            ("empty", ""),
            ("auto", "auto"),
            ("on", "on"),
            ("off", "off"),
        ):
            environment = dict(base)
            if value is None:
                environment.pop("GO111MODULE", None)
            else:
                environment["GO111MODULE"] = value

            env_result = _run(
                [go, "env", "GO111MODULE"],
                cwd=project,
                env=environment,
            )
            list_result = _run(
                [go, "list", "-mod=readonly", "-json", "."],
                cwd=project,
                env=environment,
            )
            observed[label] = {
                "go_env_GO111MODULE": (env_result.stdout or "").strip(),
                "go_env_returncode": env_result.returncode,
                "go_list_returncode": list_result.returncode,
                "go_list_stderr": (list_result.stderr or "").strip(),
            }

        checks = {
            "unset_module_mode_supports_readonly_list": observed["unset"]["go_list_returncode"] == 0,
            "empty_module_mode_supports_readonly_list": observed["empty"]["go_list_returncode"] == 0,
            "auto_module_mode_supports_readonly_list": observed["auto"]["go_list_returncode"] == 0,
            "on_module_mode_supports_readonly_list": observed["on"]["go_list_returncode"] == 0,
            "off_module_mode_rejects_readonly_module_flag": (
                observed["off"]["go_list_returncode"] != 0
                and "only valid when using modules" in observed["off"]["go_list_stderr"]
            ),
            "on_is_reported_explicitly": observed["on"]["go_env_GO111MODULE"] == "on",
            "off_is_reported_explicitly": observed["off"]["go_env_GO111MODULE"] == "off",
        }
        failures = sorted(name for name, passed in checks.items() if not passed)
        return _emit({
            "status": "ok" if not failures else "failed",
            "go": go,
            "go_version_output": version_text,
            "environment_guards": {
                "GOPROXY": "off",
                "GOWORK": "off",
                "GOSUMDB": "off",
                "GOTOOLCHAIN": "local",
                "GOENV": "off",
                "GOFLAGS": "",
                "GOROOT": "",
            },
            "checks": checks,
            "observed": observed,
            "reasons": failures,
            "project_mutated_outside_temporary_fixture": False,
            "user_goenv_mutated": False,
            "telemetry_changed": False,
            "interpretation": (
                "Characterizes GO111MODULE behavior for the candidate single-module readonly profile. "
                "Success supports explicit GO111MODULE=on as a future normalized plan input; it does not "
                "establish govulncheck source/build equivalence, freshness, or public/persisted semantics."
            ),
        }, 0 if not failures else 1)


if __name__ == "__main__":
    raise SystemExit(main())
