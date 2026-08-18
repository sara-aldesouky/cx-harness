"""Pure lifecycle tests for future write infrastructure; no business writes."""

from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.tools.context import ExecutionContext
from app.write_operations import (
    BaseWriteOperation,
    SQLAlchemyTransactionManager,
    WriteError,
    WriteExecutionContext,
    WriteExecutionContractError,
    WriteFailurePhase,
    WriteFrameworkExecutor,
    WriteResult,
    WriteSecurityBoundaryError,
    WriteSecurityEnvelope,
    WriteStatus,
    WriteTransactionError,
    WriteValidationDecision,
)


class DemoInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str


class DemoOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    normalized_value: str


class DemoOperation(BaseWriteOperation):
    name = "test_write_operation"
    version = "1.0.0"
    input_schema = DemoInput
    output_schema = DemoOutput

    def __init__(self, *, allowed=True, raises=False, invalid_output=False):
        self.allowed = allowed
        self.raises = raises
        self.invalid_output = invalid_output
        self.validation_calls = 0
        self.apply_calls = 0

    def validate(self, context, input_model):
        self.validation_calls += 1
        return (
            WriteValidationDecision.allow()
            if self.allowed
            else WriteValidationDecision.deny(
                "business_rule_denied", "The requested change is not allowed."
            )
        )

    def apply(self, context, input_model, transaction):
        self.apply_calls += 1
        transaction.append(input_model.value.strip())
        if self.raises:
            raise RuntimeError("internal database implementation detail")
        if self.invalid_output:
            return DemoInput(value="wrong-contract")
        return DemoOutput(normalized_value=input_model.value.strip())


class RecordingTransactionManager:
    def __init__(self):
        self.persisted = []
        self.starts = 0
        self.commits = 0
        self.rollbacks = 0

    def execute(self, callback):
        self.starts += 1
        pending = []
        try:
            result = callback(pending)
        except Exception as error:
            self.rollbacks += 1
            raise WriteTransactionError(
                WriteTransactionError.public_message
            ) from error
        self.persisted.extend(pending)
        self.commits += 1
        return result


class RecordingAudit:
    def __init__(self, *, raises=False):
        self.events = []
        self.raises = raises

    def record(self, event):
        if self.raises:
            raise RuntimeError("audit unavailable")
        self.events.append(event)


def context(*, authorized=True):
    return WriteExecutionContext(
        execution_context=ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            conversation_id=uuid4(),
            customer_id=uuid4(),
            principal_role="customer",
        ),
        security=WriteSecurityEnvelope(
            authenticated=authorized,
            role_policy_allowed=authorized,
            tool_authorized=authorized,
            ownership_authorized=authorized,
        ),
        request_id=uuid4(),
        correlation_id=uuid4(),
        requested_at=datetime.now(timezone.utc),
    )


def test_success_commits_once_and_returns_standard_result() -> None:
    transactions = RecordingTransactionManager()
    audit = RecordingAudit()
    operation = DemoOperation()

    result = WriteFrameworkExecutor(transactions, audit).execute(
        operation, context(), DemoInput(value=" normalized ")
    )

    assert result.status is WriteStatus.SUCCESS
    assert result.outcome == DemoOutput(normalized_value="normalized")
    assert result.error is None
    assert transactions.persisted == ["normalized"]
    assert (transactions.starts, transactions.commits, transactions.rollbacks) == (1, 1, 0)
    assert operation.validation_calls == operation.apply_calls == 1
    assert audit.events[0].status is WriteStatus.SUCCESS
    assert audit.events[0].business_change_applied is True


def test_business_validation_failure_never_starts_transaction() -> None:
    transactions = RecordingTransactionManager()
    operation = DemoOperation(allowed=False)

    result = WriteFrameworkExecutor(transactions).execute(
        operation, context(), DemoInput(value="request")
    )

    assert result.status is WriteStatus.FAILURE
    assert result.error.error_code == "business_rule_denied"
    assert result.error.phase is WriteFailurePhase.VALIDATION
    assert transactions.starts == 0
    assert operation.apply_calls == 0


def test_operation_exception_rolls_back_and_never_leaks_details() -> None:
    transactions = RecordingTransactionManager()
    result = WriteFrameworkExecutor(transactions).execute(
        DemoOperation(raises=True), context(), DemoInput(value="not-persisted")
    )

    assert result.status is WriteStatus.FAILURE
    assert result.error.error_code == "write_transaction_failed"
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert "database" not in result.model_dump_json().lower()
    assert transactions.persisted == []
    assert (transactions.commits, transactions.rollbacks) == (0, 1)


def test_invalid_outcome_contract_rolls_back_before_commit() -> None:
    transactions = RecordingTransactionManager()
    result = WriteFrameworkExecutor(transactions).execute(
        DemoOperation(invalid_output=True), context(), DemoInput(value="invalid")
    )
    assert result.error.error_code == "write_transaction_failed"
    assert transactions.persisted == []
    assert transactions.rollbacks == 1


def test_missing_stage11_authorization_fails_before_validation_or_transaction() -> None:
    transactions = RecordingTransactionManager()
    operation = DemoOperation()
    with pytest.raises(WriteSecurityBoundaryError):
        WriteFrameworkExecutor(transactions).execute(
            operation, context(authorized=False), DemoInput(value="blocked")
        )
    assert operation.validation_calls == 0
    assert transactions.starts == 0


def test_write_context_requires_trusted_customer_identity() -> None:
    with pytest.raises(ValidationError):
        WriteExecutionContext(
            execution_context=ExecutionContext(
                trace_id=uuid4(), execution_id=uuid4(), customer_id=None
            ),
            security=WriteSecurityEnvelope(
                authenticated=True,
                role_policy_allowed=True,
                tool_authorized=True,
                ownership_authorized=True,
            ),
            request_id=uuid4(), correlation_id=uuid4(),
            requested_at=datetime.now(timezone.utc),
        )


def test_write_context_rejects_naive_timestamp() -> None:
    trusted = context()
    with pytest.raises(ValidationError):
        WriteExecutionContext(
            execution_context=trusted.execution_context,
            security=trusted.security,
            request_id=uuid4(),
            correlation_id=uuid4(),
            requested_at=datetime.now(),
        )


@pytest.mark.parametrize(
    "decision",
    [
        {"allowed": True, "failure_code": "not_allowed", "public_message": "No."},
        {"allowed": False},
        {"allowed": False, "failure_code": " ", "public_message": "No."},
    ],
)
def test_validation_decision_rejects_invalid_shapes(decision) -> None:
    with pytest.raises(ValidationError):
        WriteValidationDecision(**decision)


def test_result_contract_rejects_invalid_shapes_and_metadata() -> None:
    error = WriteError(
        error_code="safe_failure",
        public_message="The request was rejected.",
        phase=WriteFailurePhase.VALIDATION,
    )
    with pytest.raises(ValidationError):
        WriteResult(status=WriteStatus.SUCCESS, message="Done.")
    with pytest.raises(ValidationError):
        WriteResult(
            status=WriteStatus.FAILURE,
            outcome=DemoOutput(normalized_value="invalid"),
            error=error,
            message="Rejected.",
        )
    with pytest.raises(TypeError):
        WriteResult(
            status=WriteStatus.SUCCESS,
            outcome=DemoOutput(normalized_value="valid"),
            message="Done.",
            metadata=["not", "a", "mapping"],
        )


@pytest.mark.parametrize(
    ("operation", "execution_context", "input_model"),
    [
        (object(), context(), DemoInput(value="value")),
        (DemoOperation(), object(), DemoInput(value="value")),
        (DemoOperation(), context(), DemoOutput(normalized_value="value")),
    ],
)
def test_executor_rejects_invalid_contract_inputs(
    operation, execution_context, input_model
) -> None:
    with pytest.raises(WriteExecutionContractError):
        WriteFrameworkExecutor(RecordingTransactionManager()).execute(
            operation, execution_context, input_model
        )


class InvalidValidationOperation(DemoOperation):
    def validate(self, context, input_model):
        return True


def test_executor_rejects_invalid_validation_return() -> None:
    with pytest.raises(WriteExecutionContractError):
        WriteFrameworkExecutor(RecordingTransactionManager()).execute(
            InvalidValidationOperation(), context(), DemoInput(value="value")
        )


class ExplodingValidationOperation(DemoOperation):
    def validate(self, context, input_model):
        raise RuntimeError("private repository connection detail")


def test_validation_repository_failure_is_safe_and_never_opens_transaction() -> None:
    transactions = RecordingTransactionManager()
    audit = RecordingAudit()
    result = WriteFrameworkExecutor(transactions, audit).execute(
        ExplodingValidationOperation(), context(), DemoInput(value="value")
    )
    assert result.error.phase is WriteFailurePhase.INFRASTRUCTURE
    assert result.error.error_code == "write_infrastructure_failed"
    assert transactions.starts == 0
    assert "repository" not in result.model_dump_json().lower()
    assert audit.events[0].failure_phase is WriteFailurePhase.INFRASTRUCTURE


class FailingInfrastructureManager:
    def execute(self, callback):
        raise RuntimeError("connection string and internal details")


def test_infrastructure_failure_is_safe_and_standardized() -> None:
    result = WriteFrameworkExecutor(FailingInfrastructureManager()).execute(
        DemoOperation(), context(), DemoInput(value="value")
    )
    assert result.error.phase is WriteFailurePhase.INFRASTRUCTURE
    assert result.error.error_code == "write_infrastructure_failed"
    assert "connection" not in result.model_dump_json().lower()


def test_audit_failure_does_not_change_committed_result() -> None:
    transactions = RecordingTransactionManager()
    result = WriteFrameworkExecutor(
        transactions, RecordingAudit(raises=True)
    ).execute(DemoOperation(), context(), DemoInput(value="safe"))
    assert result.status is WriteStatus.SUCCESS
    assert transactions.persisted == ["safe"]


def test_results_are_immutable_json_serializable_and_deterministic() -> None:
    result = WriteFrameworkExecutor(RecordingTransactionManager()).execute(
        DemoOperation(), context(), DemoInput(value="stable")
    )
    assert result.model_dump_json() == result.model_dump_json()
    assert isinstance(result.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        result.metadata["changed"] = True
    with pytest.raises(ValidationError):
        result.message = "changed"


class FakeBegin:
    def __init__(self, owner):
        self.owner = owner
        self.resource = []

    def __enter__(self):
        self.owner.started += 1
        return self.resource

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.owner.committed += 1
            self.owner.persisted.extend(self.resource)
        else:
            self.owner.rolled_back += 1
        return False


class FakeSessionFactory:
    def __init__(self):
        self.started = self.committed = self.rolled_back = 0
        self.persisted = []

    def begin(self):
        return FakeBegin(self)


def test_sqlalchemy_adapter_owns_commit_and_rollback_lifecycle() -> None:
    factory = FakeSessionFactory()
    manager = SQLAlchemyTransactionManager(factory)
    assert manager.execute(lambda session: session.append("committed") or 1) == 1
    assert factory.persisted == ["committed"]
    assert factory.committed == 1

    with pytest.raises(WriteTransactionError) as caught:
        manager.execute(lambda session: (_ for _ in ()).throw(RuntimeError("sql")))
    assert str(caught.value) == WriteTransactionError.public_message
    assert factory.rolled_back == 1
