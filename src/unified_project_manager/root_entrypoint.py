from __future__ import annotations

import sys

from .batch_operation_entrypoint import dispatch_batch_operation_command


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    batch_result = dispatch_batch_operation_command(arguments)
    if batch_result is not None:
        return batch_result

    from .entrypoint import main as existing_main

    return existing_main(arguments)
