from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.policy import PolicyError, evaluate_policy, load_policy


class PolicyTests(unittest.TestCase):
    def _npm(self, root: Path, *, lock: bool = True) -> None:
        (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        if lock:
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def test_missing_config_is_permissive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm(root)
            report = evaluate_policy(discover(root))
            self.assertTrue(report.passed)

    def test_require_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm(root, lock=False)
            (root / "upm.toml").write_text("[policy]\nrequire_lockfiles = true\n", encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.lockfile-required", {item.code for item in report.violations})

    def test_manager_allow_and_deny_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm(root)
            (root / "upm.toml").write_text('[policy]\nallowed_managers=["pnpm"]\n', encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.manager-not-allowed", {item.code for item in report.violations})
            (root / "upm.toml").write_text('[policy]\ndenied_managers=["npm"]\n', encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.manager-denied", {item.code for item in report.violations})

    def test_snapshot_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm(root)
            (root / "upm.toml").write_text("[policy]\nrequire_integrity_snapshot=true\n", encoding="utf-8")
            self.assertFalse(evaluate_policy(discover(root)).passed)
            state = root / ".upm" / "state.json"
            state.parent.mkdir()
            state.write_text("{}", encoding="utf-8")
            self.assertTrue(evaluate_policy(discover(root)).passed)

    def test_native_verification_coverage_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("requests==2\n", encoding="utf-8")
            (root / "upm.toml").write_text("[policy]\nrequire_native_verification=true\n", encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.native-verification-required", {item.code for item in report.violations})

    def test_warning_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm(root, lock=False)
            (root / "upm.toml").write_text("[policy]\nmax_warnings=0\n", encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.warning-budget-exceeded", {item.code for item in report.violations})

    def test_error_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text("not = [valid", encoding="utf-8")
            (root / "upm.toml").write_text("[policy]\nmax_errors=0\n", encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.error-budget-exceeded", {item.code for item in report.violations})

    def test_invalid_policy_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('[policy]\nrequire_lockfiles="yes"\n', encoding="utf-8")
            with self.assertRaisesRegex(PolicyError, "must be a boolean"):
                load_policy(root)

    def test_manager_cannot_be_allowed_and_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "upm.toml").write_text('[policy]\nallowed_managers=["npm"]\ndenied_managers=["npm"]\n', encoding="utf-8")
            with self.assertRaisesRegex(PolicyError, "both allowed and denied"):
                load_policy(root)


if __name__ == "__main__":
    unittest.main()
