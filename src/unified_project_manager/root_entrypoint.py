from __future__ import annotations

import sys

from .batch_operation_entrypoint import dispatch_batch_operation_command
from .exec_receipt_entrypoint import dispatch_exec_receipt_command
from .fleet_status_entrypoint import dispatch_fleet_status_command
from .init_receipt_entrypoint import dispatch_init_receipt_command
from .operation_receipt_entrypoint import dispatch_operation_receipt_command
from .package_plan import dispatch_package_plan_command
from .receipt_entrypoint import dispatch_receipt_command
from .repair_receipt_entrypoint import dispatch_repair_receipt_command


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    package_plan_result = dispatch_package_plan_command(arguments)
    if package_plan_result is not None:
        return package_plan_result
    batch_result = dispatch_batch_operation_command(arguments)
    if batch_result is not None:
        return batch_result
    operation_result = dispatch_operation_receipt_command(arguments)
    if operation_result is not None:
        return operation_result
    exec_result = dispatch_exec_receipt_command(arguments)
    if exec_result is not None:
        return exec_result
    repair_result = dispatch_repair_receipt_command(arguments)
    if repair_result is not None:
        return repair_result
    init_result = dispatch_init_receipt_command(arguments)
    if init_result is not None:
        return init_result
    fleet_status_result = dispatch_fleet_status_command(arguments)
    if fleet_status_result is not None:
        return fleet_status_result
    receipt_result = dispatch_receipt_command(arguments)
    if receipt_result is not None:
        return receipt_result

    from .entrypoint import main as existing_main

    return existing_main(arguments)
