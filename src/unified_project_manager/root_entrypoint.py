from __future__ import annotations

import sys

from .batch_operation_entrypoint import dispatch_batch_operation_command
from .exec_receipt_entrypoint import dispatch_exec_receipt_command
from .operation_receipt_entrypoint import dispatch_operation_receipt_command


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    batch_result = dispatch_batch_operation_command(arguments)
    if batch_result is not None:
        return batch_result
    operation_result = dispatch_operation_receipt_command(arguments)
    if operation_result is not None:
        return operation_result
    exec_result = dispatch_exec_receipt_command(arguments)
    if exec_result is not None:
        return exec_result

    from .entrypoint import main as existing_main

    return existing_main(arguments)
