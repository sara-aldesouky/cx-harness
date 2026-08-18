"""Central execution lifecycle for every future business write operation."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from app.write_operations.contracts import (
    BaseWriteOperation,
    WriteAuditEvent,
    WriteError,
    WriteExecutionContext,
    WriteFailurePhase,
    WriteResult,
    WriteStatus,
    WriteValidationDecision,
)
from app.write_operations.transaction import TransactionManager, WriteTransactionError


class WriteExecutionContractError(TypeError):
    """Raised before transactions when an operation violates its declaration."""


class WriteSecurityBoundaryError(PermissionError):
    """Fail closed when existing Stage 11 gates have not all authorized."""


class WriteAuditObserver(Protocol):
    def record(self, event: WriteAuditEvent) -> None: ...


class NullWriteAuditObserver:
    def record(self, event: WriteAuditEvent) -> None:
        return None


TransactionT = TypeVar("TransactionT")


class WriteFrameworkExecutor(Generic[TransactionT]):
    """Coordinate security proof, validation, transaction, audit, and result."""

    def __init__(
        self,
        transaction_manager: TransactionManager[TransactionT],
        audit_observer: WriteAuditObserver | None = None,
    ) -> None:
        if not callable(getattr(transaction_manager, "execute", None)):
            raise TypeError("transaction_manager must provide execute()")
        observer = audit_observer or NullWriteAuditObserver()
        if not callable(getattr(observer, "record", None)):
            raise TypeError("audit_observer must provide record()")
        self._transactions = transaction_manager
        self._audit = observer

    def execute(
        self,
        operation: BaseWriteOperation,
        context: WriteExecutionContext,
        input_model: BaseModel,
    ) -> WriteResult[BaseModel]:
        if not isinstance(operation, BaseWriteOperation):
            raise WriteExecutionContractError(
                "operation must implement BaseWriteOperation"
            )
        if not isinstance(context, WriteExecutionContext):
            raise WriteExecutionContractError(
                "context must be a WriteExecutionContext"
            )
        if not context.security.fully_authorized:
            raise WriteSecurityBoundaryError(
                "write operation did not pass all security gates"
            )
        if not isinstance(input_model, operation.input_schema):
            raise WriteExecutionContractError(
                f"input_model must be {operation.input_schema.__name__}"
            )

        try:
            decision = operation.validate(context, input_model)
        except Exception:
            result = WriteResult(
                status=WriteStatus.FAILURE,
                error=WriteError(
                    error_code="write_infrastructure_failed",
                    public_message="The requested change is temporarily unavailable.",
                    phase=WriteFailurePhase.INFRASTRUCTURE,
                ),
                message="The requested change is temporarily unavailable.",
            )
            self._record(operation, context, input_model, result)
            return result
        if not isinstance(decision, WriteValidationDecision):
            raise WriteExecutionContractError(
                "write validation must return WriteValidationDecision"
            )
        if not decision.allowed:
            result = WriteResult(
                status=WriteStatus.FAILURE,
                error=WriteError(
                    error_code=decision.failure_code,
                    public_message=decision.public_message,
                    phase=WriteFailurePhase.VALIDATION,
                ),
                message=decision.public_message,
            )
            self._record(operation, context, input_model, result)
            return result

        try:
            outcome = self._transactions.execute(
                lambda transaction: self._apply_and_validate(
                    operation, context, input_model, transaction
                )
            )
        except WriteTransactionError:
            result = WriteResult(
                status=WriteStatus.FAILURE,
                error=WriteError(
                    error_code="write_transaction_failed",
                    public_message=WriteTransactionError.public_message,
                    phase=WriteFailurePhase.TRANSACTION,
                ),
                message=WriteTransactionError.public_message,
            )
            self._record(operation, context, input_model, result)
            return result
        except Exception:
            result = WriteResult(
                status=WriteStatus.FAILURE,
                error=WriteError(
                    error_code="write_infrastructure_failed",
                    public_message="The requested change is temporarily unavailable.",
                    phase=WriteFailurePhase.INFRASTRUCTURE,
                ),
                message="The requested change is temporarily unavailable.",
            )
            self._record(operation, context, input_model, result)
            return result

        result = WriteResult(
            status=WriteStatus.SUCCESS,
            outcome=outcome,
            message=operation.success_message(outcome),
        )
        self._record(operation, context, input_model, result)
        return result

    @staticmethod
    def _apply_and_validate(operation, context, input_model, transaction):
        outcome = operation.apply(context, input_model, transaction)
        if not isinstance(outcome, operation.output_schema):
            raise WriteTransactionError(
                WriteTransactionError.public_message
            )
        return outcome

    def _record(
        self,
        operation: BaseWriteOperation,
        context: WriteExecutionContext,
        input_model: BaseModel,
        result: WriteResult,
    ) -> None:
        try:
            self._audit.record(
                WriteAuditEvent(
                    operation_name=operation.name,
                    operation_version=operation.version,
                    request_id=context.request_id,
                    correlation_id=context.correlation_id,
                    resource_reference=operation.audit_reference(
                        input_model, result.outcome
                    ),
                    status=result.status,
                    business_change_applied=(
                        operation.business_change_applied(result.outcome)
                        if result.outcome is not None
                        else None
                    ),
                    failure_phase=(result.error.phase if result.error else None),
                    failure_code=(result.error.error_code if result.error else None),
                )
            )
        except Exception:
            # Stage 11 audit resilience remains unchanged: observer failure does
            # not transform an already committed or safely rejected operation.
            pass
