"""Framework ownership and failure-boundary tests for every write operation."""

import ast
import inspect

import pytest

from app.write_operations import (
    CancelOrderOperation,
    CreateSupportTicketOperation,
    InitiateRefundOperation,
    UpdateDeliveryAddressOperation,
    WriteFailurePhase,
    WriteFrameworkExecutor,
)


OPERATIONS = (
    CancelOrderOperation,
    UpdateDeliveryAddressOperation,
    InitiateRefundOperation,
    CreateSupportTicketOperation,
)


@pytest.mark.parametrize("operation_type", OPERATIONS)
def test_business_operations_do_not_manage_transactions(operation_type) -> None:
    tree = ast.parse(inspect.getsource(operation_type))
    forbidden = {"commit", "rollback", "flush", "begin"}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called.isdisjoint(forbidden)


@pytest.mark.parametrize("operation_type", OPERATIONS)
def test_every_operation_declares_the_shared_framework_contract(operation_type) -> None:
    assert operation_type.name
    assert operation_type.version == "1.0.0"
    assert operation_type.input_schema.model_config.get("frozen") is True
    assert operation_type.output_schema.model_config.get("frozen") is True


class InfrastructureFailureManager:
    def __init__(self, error):
        self.error = error

    def execute(self, callback):
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private timeout"),
        RuntimeError("database unavailable"),
        RuntimeError("serialization conflict"),
    ],
)
def test_transaction_infrastructure_failures_are_standardized(error) -> None:
    from tests.write_operations.test_write_framework import DemoInput, DemoOperation, context

    result = WriteFrameworkExecutor(InfrastructureFailureManager(error)).execute(
        DemoOperation(), context(), DemoInput(value="safe")
    )
    assert result.error.phase is WriteFailurePhase.INFRASTRUCTURE
    assert result.error.error_code == "write_infrastructure_failed"
    assert str(error) not in result.model_dump_json()
