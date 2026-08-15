from __future__ import annotations

import unittest
from unittest.mock import patch

from unified_project_manager.extended_entrypoint import main


class ExtendedEntrypointTests(unittest.TestCase):
    def test_routes_new_control_plane_commands_without_touching_legacy_dispatch(self) -> None:
        cases = (
            ("update", "unified_project_manager.extended_entrypoint.update_main"),
            ("dedupe", "unified_project_manager.extended_entrypoint.dedupe_main"),
            ("env", "unified_project_manager.extended_entrypoint.environment_main"),
            ("duplicates", "unified_project_manager.extended_entrypoint.duplicates_main"),
            ("duplicates-physical", "unified_project_manager.extended_entrypoint.physical_duplicates_main"),
            ("tools", "unified_project_manager.extended_entrypoint.tools_main"),
            ("tools-state", "unified_project_manager.extended_entrypoint.tools_state_main"),
            ("audit-v2", "unified_project_manager.extended_entrypoint.advisory_v2_main"),
            ("advisory-v2-status", "unified_project_manager.extended_entrypoint.advisory_v2_status_main"),
        )
        for command, target in cases:
            with self.subTest(command=command), patch(target, return_value=17) as routed, patch(
                "unified_project_manager.root_entrypoint.main",
                return_value=91,
            ) as legacy:
                code = main([command, "one", "two"])
                self.assertEqual(code, 17)
                routed.assert_called_once_with(["one", "two"])
                legacy.assert_not_called()

    def test_evidence_routes_manifest_validate_and_semantic_verify_separately(self) -> None:
        with patch(
            "unified_project_manager.extended_entrypoint.evidence_manifest_main",
            return_value=11,
        ) as manifest, patch(
            "unified_project_manager.extended_entrypoint.evidence_verify_main",
            return_value=12,
        ) as verify:
            self.assertEqual(main(["evidence", "manifest", ".", "--json"]), 11)
            manifest.assert_called_once_with(["manifest", ".", "--json"])
            verify.assert_not_called()

        with patch(
            "unified_project_manager.extended_entrypoint.evidence_manifest_main",
            return_value=11,
        ) as manifest, patch(
            "unified_project_manager.extended_entrypoint.evidence_verify_main",
            return_value=12,
        ) as verify:
            self.assertEqual(main(["evidence", "verify", ".", "--json"]), 12)
            verify.assert_called_once_with([".", "--json"])
            manifest.assert_not_called()

    def test_unknown_command_falls_through_to_existing_root_entrypoint_unchanged(self) -> None:
        arguments = ["status", ".", "--json"]
        with patch(
            "unified_project_manager.root_entrypoint.main",
            return_value=23,
        ) as legacy:
            code = main(arguments)
        self.assertEqual(code, 23)
        legacy.assert_called_once_with(arguments)

    def test_empty_argv_falls_through_to_existing_root_entrypoint(self) -> None:
        with patch(
            "unified_project_manager.root_entrypoint.main",
            return_value=24,
        ) as legacy:
            code = main([])
        self.assertEqual(code, 24)
        legacy.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
