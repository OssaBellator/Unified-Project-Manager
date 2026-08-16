from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any


BUILD_ENV_KEYS = (
    "GOOS",
    "GOARCH",
    "GOROOT",
    "CGO_ENABLED",
    "GOFLAGS",
    "GOEXPERIMENT",
    "GOAMD64",
    "GOARM64",
    "GOARM",
    "GO386",
    "GOMIPS",
    "GOMIPS64",
    "GOPPC64",
    "GORISCV64",
    "GOWASM",
    "CC",
    "CXX",
    "PKG_CONFIG",
    "CGO_CFLAGS",
    "CGO_CPPFLAGS",
    "CGO_CXXFLAGS",
    "CGO_FFLAGS",
    "CGO_LDFLAGS",
)


def _emit(payload: dict[str, Any], code: int) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


def _run(argv: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
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
            "interpretation": "Build-environment default characterization did not run; blocked is not a pass.",
        }, 2)

    version = _run([go, "version"], env=dict(os.environ))
    version_text = (version.stdout or version.stderr or "").strip()
    minor = _go_minor(version_text)
    if version.returncode != 0 or minor is None or minor < 21:
        return _emit({
            "status": "blocked",
            "go": go,
            "go_version_output": version_text,
            "reasons": ["Go 1.21+ is required for the candidate source-observation profile"],
            "interpretation": "Build-environment default characterization did not run; blocked is not a pass.",
        }, 2)

    baseline_env = dict(os.environ)
    for key in BUILD_ENV_KEYS:
        baseline_env.pop(key, None)
    baseline_env.update({
        "GOPROXY": "off",
        "GOWORK": "off",
        "GOSUMDB": "off",
        "GOTOOLCHAIN": "local",
        "GOENV": "off",
    })

    baseline_result = _run([go, "env", "-json", *BUILD_ENV_KEYS], env=baseline_env)
    if baseline_result.returncode != 0:
        detail = (baseline_result.stderr or baseline_result.stdout or "").strip()
        return _emit({
            "status": "failed",
            "go": go,
            "go_version_output": version_text,
            "reasons": [f"baseline `go env -json` failed with exit {baseline_result.returncode}: {detail}"],
        }, 1)
    try:
        baseline = json.loads(baseline_result.stdout or "")
    except json.JSONDecodeError as exc:
        return _emit({
            "status": "failed",
            "go": go,
            "go_version_output": version_text,
            "reasons": [f"baseline `go env -json` returned invalid JSON: {exc}"],
        }, 1)
    if not isinstance(baseline, dict):
        return _emit({
            "status": "failed",
            "go": go,
            "go_version_output": version_text,
            "reasons": ["baseline `go env -json` returned a non-object"],
        }, 1)

    checks: dict[str, bool] = {}
    mismatches: dict[str, dict[str, str | int]] = {}
    for key in BUILD_ENV_KEYS:
        environment = dict(baseline_env)
        environment[key] = ""
        result = _run([go, "env", key], env=environment)
        observed = (result.stdout or "").strip()
        expected_value = baseline.get(key)
        expected = expected_value if isinstance(expected_value, str) else ""
        passed = result.returncode == 0 and observed == expected
        checks[key] = passed
        if not passed:
            mismatches[key] = {
                "returncode": result.returncode,
                "expected": expected,
                "observed": observed,
                "stderr": (result.stderr or "").strip(),
            }

    failures = sorted(key for key, passed in checks.items() if not passed)
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
        },
        "checks": checks,
        "mismatches": mismatches,
        "reasons": failures,
        "user_goenv_mutated": False,
        "telemetry_changed": False,
        "interpretation": (
            "Characterizes only whether explicit empty process values reproduce the unset/default `go env` "
            "resolution for retained build inputs under GOENV=off. Success does not establish govulncheck "
            "source/build equivalence, freshness, or safe broader plan serialization."
        ),
    }, 0 if not failures else 1)


if __name__ == "__main__":
    raise SystemExit(main())
