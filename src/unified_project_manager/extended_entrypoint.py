from __future__ import annotations

import sys

from .advisory_v2_entrypoint import main as advisory_v2_main
from .advisory_v2_status_entrypoint import main as advisory_v2_status_main
from .dedupe_entrypoint import main as dedupe_main
from .duplicate_entrypoint import main as duplicates_main
from .environment_entrypoint import main as environment_main
from .evidence_manifest_entrypoint import main as evidence_manifest_main
from .evidence_semantics_entrypoint import main as evidence_verify_main
from .physical_duplicate_entrypoint import main as physical_duplicates_main
from .tool_resolution_entrypoint import main as tools_main
from .tool_resolution_state_entrypoint import main as tools_state_main
from .update_entrypoint import main as update_main


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        from .root_entrypoint import main as root_main

        return root_main(arguments)

    command = arguments[0]
    rest = arguments[1:]

    if command == "update":
        return update_main(rest)
    if command == "dedupe":
        return dedupe_main(rest)
    if command == "env":
        return environment_main(rest)
    if command == "duplicates":
        return duplicates_main(rest)
    if command == "duplicates-physical":
        return physical_duplicates_main(rest)
    if command == "tools":
        return tools_main(rest)
    if command == "tools-state":
        return tools_state_main(rest)
    if command == "audit-v2":
        return advisory_v2_main(rest)
    if command == "advisory-v2-status":
        return advisory_v2_status_main(rest)
    if command == "evidence":
        if rest and rest[0] == "verify":
            return evidence_verify_main(rest[1:])
        return evidence_manifest_main(rest)

    from .root_entrypoint import main as root_main

    return root_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
