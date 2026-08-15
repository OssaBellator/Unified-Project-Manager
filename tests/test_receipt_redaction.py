from __future__ import annotations

import unittest

from unified_project_manager.receipts import redact_argv


class ReceiptRedactionTests(unittest.TestCase):
    def test_sensitive_flags_and_assignments_are_redacted(self) -> None:
        argv = redact_argv([
            "npm", "config", "set",
            "--token", "secret-token",
            "//registry.example/:_authToken=another-secret",
            "password=hunter2",
        ])
        self.assertEqual(argv[3:5], ("--token", "<redacted>"))
        self.assertIn("//registry.example/:_authToken=<redacted>", argv)
        self.assertIn("password=<redacted>", argv)
        rendered = " ".join(argv)
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("another-secret", rendered)
        self.assertNotIn("hunter2", rendered)

    def test_url_userinfo_is_removed_for_credential_bearing_urls(self) -> None:
        argv = redact_argv([
            "npm",
            "install",
            "https://alice:password@example.invalid/private/pkg.tgz?download=1#fragment",
            "git+https://token-value@example.invalid/org/repo.git",
        ])
        self.assertEqual(
            argv[2],
            "https://<redacted>@example.invalid/private/pkg.tgz?download=1#fragment",
        )
        self.assertEqual(
            argv[3],
            "git+https://<redacted>@example.invalid/org/repo.git",
        )
        rendered = " ".join(argv)
        self.assertNotIn("alice", rendered)
        self.assertNotIn("password", rendered)
        self.assertNotIn("token-value", rendered)

    def test_authorization_headers_are_redacted(self) -> None:
        argv = redact_argv([
            "tool",
            "-H",
            "Authorization: Bearer top-secret",
            "Proxy-Authorization: Basic hidden",
            "Accept: application/json",
        ])
        self.assertEqual(argv[2], "Authorization: <redacted>")
        self.assertEqual(argv[3], "Proxy-Authorization: <redacted>")
        self.assertEqual(argv[4], "Accept: application/json")
        self.assertNotIn("top-secret", " ".join(argv))
        self.assertNotIn("hidden", " ".join(argv))

    def test_noncredential_git_ssh_user_is_not_misclassified(self) -> None:
        argv = redact_argv(["git", "clone", "git@github.com:org/repo.git"])
        self.assertEqual(argv[-1], "git@github.com:org/repo.git")


if __name__ == "__main__":
    unittest.main()
