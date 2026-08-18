from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.argument_binding import (
    ArgumentBindingPolicyRegistry,
    ArgumentBindingRequest,
    ArgumentSource,
    BindingAuditMetadata,
    BindingStartupValidationError,
    BindingStatus,
    PolicySchemaCompatibilityValidator,
    ProviderToolSelection,
    RegisteredToolSchema,
    RegistryCompletenessValidator,
    ToolBindingPolicy,
    ToolSchemaArgument,
    TrustedArgumentBinder,
    TrustedExecutionValues,
    build_write_argument_binding_policy_registry,
    write_tool_binding_policies,
)
from app.entity_resolution.contracts import (
    EntityResolutionResult,
    ResolutionStatus,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000001")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000002")


def schema(
    name: str,
    arguments: tuple[tuple[str, bool, bool], ...],
    *,
    executable: bool = True,
    write: bool = True,
) -> RegisteredToolSchema:
    return RegisteredToolSchema(
        tool_name=name,
        arguments=tuple(
            ToolSchemaArgument(name=argument, required=required, protected=protected)
            for argument, required, protected in arguments
        ),
        executable=executable,
        write_operation=write,
    )


def write_schemas() -> tuple[RegisteredToolSchema, ...]:
    return (
        schema("cancel_order", (("order_number", True, True),)),
        schema(
            "update_delivery_address",
            (("order_number", True, True), ("delivery_address", True, False)),
        ),
        schema("initiate_refund", (("order_number", True, True),)),
        schema(
            "create_support_ticket",
            (
                ("category", True, False),
                ("issue_description", True, False),
                ("escalation_reason", True, False),
                ("order_number", False, True),
            ),
        ),
    )


def binding_request(tool_name: str = "cancel_order") -> ArgumentBindingRequest:
    return ArgumentBindingRequest(
        selection=ProviderToolSelection(
            tool_name=tool_name,
            arguments={"order_number": "fabricated-private-value"},
        ),
        trusted_values=TrustedExecutionValues(
            customer_id=CUSTOMER_ID,
            conversation_id=CONVERSATION_ID,
        ),
        current_customer_message="cancel my order",
    )


class ResolverBehavior:
    def __init__(self, value=None, error=None) -> None:
        self.value = value
        self.error = error
        self.calls = 0
        self._lock = Lock()

    def resolve(self, request):
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


def resolved_result() -> EntityResolutionResult:
    return EntityResolutionResult(
        status=ResolutionStatus.RESOLVED,
        resolved_entity={
            "entity_type": "order",
            "public_reference": "ORD-10025",
            "relationship": "active",
            "verification_source": "repository_lookup",
            "verified_at": NOW,
        },
        public_message="resolved",
    )


def test_current_write_policies_are_schema_compatible() -> None:
    validator = PolicySchemaCompatibilityValidator()
    for policy, descriptor in zip(write_tool_binding_policies(), write_schemas()):
        validator.validate(policy, descriptor)


def test_compatibility_rejects_tool_mismatch_and_orphan_inserted_argument() -> None:
    validator = PolicySchemaCompatibilityValidator()
    policy = write_tool_binding_policies()[0]
    with pytest.raises(BindingStartupValidationError, match="tool names"):
        validator.validate(policy, schema("different", (("order_number", True, True),)))
    with pytest.raises(BindingStartupValidationError, match="absent"):
        validator.validate(policy, schema("cancel_order", ()))


def test_compatibility_rejects_protection_mismatch_and_invalid_sideband() -> None:
    validator = PolicySchemaCompatibilityValidator()
    policy = write_tool_binding_policies()[0]
    with pytest.raises(BindingStartupValidationError, match="classification"):
        validator.validate(
            policy, schema("cancel_order", (("order_number", True, False),))
        )
    invalid_sideband = policy.model_copy(
        update={
            "argument_policies": tuple(
                item.model_copy(
                    update={"include_in_tool_arguments": False}
                )
                if item.argument_name == "order_number"
                else item
                for item in policy.argument_policies
            )
        }
    )
    with pytest.raises(BindingStartupValidationError, match="orphan"):
        validator.validate(
            invalid_sideband,
            schema("cancel_order", (("order_number", True, True),)),
        )


def test_compatibility_rejects_missing_required_schema_argument() -> None:
    validator = PolicySchemaCompatibilityValidator()
    policy = write_tool_binding_policies()[0]
    descriptor = schema(
        "cancel_order",
        (("order_number", True, True), ("required_new_field", True, False)),
    )
    with pytest.raises(BindingStartupValidationError, match="required schema"):
        validator.validate(policy, descriptor)


def test_compatibility_contract_type_validation() -> None:
    validator = PolicySchemaCompatibilityValidator()
    policy = write_tool_binding_policies()[0]
    descriptor = write_schemas()[0]
    with pytest.raises(TypeError, match="ToolBindingPolicy"):
        validator.validate(object(), descriptor)
    with pytest.raises(TypeError, match="RegisteredToolSchema"):
        validator.validate(policy, object())


def test_registry_completeness_accepts_exact_write_coverage() -> None:
    RegistryCompletenessValidator().validate(
        build_write_argument_binding_policy_registry(), write_schemas()
    )


def test_registry_completeness_rejects_duplicate_schema_missing_and_orphan_policy() -> None:
    validator = RegistryCompletenessValidator()
    registry = build_write_argument_binding_policy_registry()
    schemas = write_schemas()
    with pytest.raises(BindingStartupValidationError, match="duplicated"):
        validator.validate(registry, schemas + (schemas[0],))
    with pytest.raises(BindingStartupValidationError, match="missing a policy"):
        validator.validate(ArgumentBindingPolicyRegistry(), schemas)
    with pytest.raises(BindingStartupValidationError, match="orphan"):
        validator.validate(registry, schemas[:-1])


def test_nonwrite_or_nonexecutable_schema_does_not_require_policy() -> None:
    RegistryCompletenessValidator().validate(
        ArgumentBindingPolicyRegistry(),
        (
            schema("read_tool", (), write=False),
            schema("disabled_write", (), executable=False),
        ),
    )


def test_registry_completeness_contract_type_validation() -> None:
    with pytest.raises(TypeError, match="compatibility_validator"):
        RegistryCompletenessValidator(object())
    validator = RegistryCompletenessValidator()
    with pytest.raises(TypeError, match="ArgumentBindingPolicyRegistry"):
        validator.validate(object(), ())
    with pytest.raises(TypeError, match="schemas must be a tuple"):
        validator.validate(ArgumentBindingPolicyRegistry(), [])
    with pytest.raises(TypeError, match="schemas must be a tuple"):
        validator.validate(ArgumentBindingPolicyRegistry(), (object(),))


def test_schema_descriptor_validation_and_immutability() -> None:
    descriptor = schema(" tool ", ((" value ", True, False),))
    assert descriptor.tool_name == "tool"
    assert descriptor.arguments[0].name == "value"
    with pytest.raises(ValidationError, match="name must not be empty"):
        ToolSchemaArgument(name=" ", required=True)
    with pytest.raises(ValidationError, match="tool_name"):
        RegisteredToolSchema(tool_name=" ", arguments=())
    duplicate = ToolSchemaArgument(name="x", required=True)
    with pytest.raises(ValidationError, match="unique"):
        RegisteredToolSchema(
            tool_name="tool", arguments=(duplicate, duplicate)
        )
    with pytest.raises(ValidationError):
        descriptor.tool_name = "changed"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("private timeout"), "resolver_timeout"),
        (FutureCancelledError("private cancellation"), "resolver_cancelled"),
        (RuntimeError("private repository detail"), "resolver_unavailable"),
    ],
)
def test_resolver_exceptions_are_safe_and_fail_closed(error, code) -> None:
    result = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(),
        ResolverBehavior(error=error),
    ).bind(binding_request())
    assert result.status is BindingStatus.RESOLUTION_FAILED
    assert result.bound_selection is None
    assert result.failure.code == code
    assert result.failure.public_message == "Order resolution is temporarily unavailable."
    serialized = result.model_dump_json()
    assert "private" not in serialized
    assert "fabricated" not in serialized


def test_active_asyncio_cancellation_propagates_without_a_result() -> None:
    cancellation = AsyncCancelledError("active task cancellation")
    binder = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(),
        ResolverBehavior(error=cancellation),
    )
    with pytest.raises(AsyncCancelledError) as raised:
        binder.bind(binding_request())
    assert raised.value is cancellation


@pytest.mark.parametrize("signal", [KeyboardInterrupt(), SystemExit()])
def test_process_control_signals_propagate(signal) -> None:
    binder = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(), ResolverBehavior(error=signal)
    )
    with pytest.raises(type(signal)) as raised:
        binder.bind(binding_request())
    assert raised.value is signal


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (object(), "invalid_resolver_response"),
        (
            EntityResolutionResult.model_construct(
                status="unknown",
                resolved_entity=None,
                candidates=(),
                mentions=(),
                error_code=None,
                public_message="unsafe internal detail",
                state_revision=None,
            ),
            "invalid_resolver_contract",
        ),
        (
            EntityResolutionResult.model_construct(
                status=ResolutionStatus.RESOLVED,
                resolved_entity=None,
                candidates=(),
                mentions=(),
                error_code=None,
                public_message="unsafe internal detail",
                state_revision=None,
            ),
            "invalid_resolver_contract",
        ),
    ],
)
def test_malformed_resolver_responses_fail_closed(response, code) -> None:
    result = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(), ResolverBehavior(value=response)
    ).bind(binding_request())
    assert result.status is BindingStatus.RESOLUTION_FAILED
    assert result.failure.code == code
    assert "unsafe" not in result.model_dump_json()


def test_trusted_execution_extensions_are_immutable_and_backward_compatible() -> None:
    legacy = TrustedExecutionValues(
        customer_id=CUSTOMER_ID, conversation_id=CONVERSATION_ID
    )
    mutable = {"region_hint": {"labels": ["cairo"]}}
    extended = TrustedExecutionValues(
        customer_id=CUSTOMER_ID,
        conversation_id=CONVERSATION_ID,
        extensions=mutable,
    )
    mutable["region_hint"]["labels"].append("changed")
    assert legacy.extensions == {}
    assert extended.extensions == {"region_hint": {"labels": ("cairo",)}}
    assert extended.model_dump(mode="json")["extensions"] == {
        "region_hint": {"labels": ["cairo"]}
    }
    with pytest.raises(ValidationError):
        extended.customer_id = UUID(int=0)


def test_success_audit_metadata_is_sanitized_and_deterministic() -> None:
    result = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(),
        ResolverBehavior(value=resolved_result()),
    ).bind(binding_request())
    audit = result.audit_metadata
    assert audit.binding_status is BindingStatus.BOUND
    assert audit.protected_argument_count == 3
    assert audit.injected_argument_count == 2
    assert audit.replaced_argument_count == 1
    assert audit.provenance_categories == (
        ArgumentSource.EXECUTION_CONTEXT,
        ArgumentSource.VERIFIED_ENTITY_RESOLUTION,
    )
    assert audit.resolver_outcome is ResolutionStatus.RESOLVED
    serialized = audit.model_dump_json()
    for forbidden in (
        str(CUSTOMER_ID),
        str(CONVERSATION_ID),
        "ORD-10025",
        "fabricated",
        "cancel my order",
    ):
        assert forbidden not in serialized
    assert serialized == audit.model_dump_json()


def test_failure_audit_contains_only_safe_counts_and_outcome() -> None:
    not_found = EntityResolutionResult(
        status=ResolutionStatus.NOT_FOUND,
        error_code="order_not_found",
        public_message="Order not found.",
    )
    result = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(),
        ResolverBehavior(value=not_found),
    ).bind(binding_request())
    audit = result.audit_metadata
    assert audit.protected_argument_count == 3
    assert audit.injected_argument_count == audit.replaced_argument_count == 0
    assert audit.provenance_categories == ()
    assert audit.resolver_outcome is ResolutionStatus.NOT_FOUND


def test_audit_contract_normalizes_categories_and_rejects_negative_counts() -> None:
    audit = BindingAuditMetadata(
        binding_status=BindingStatus.BOUND,
        protected_argument_count=1,
        injected_argument_count=1,
        replaced_argument_count=0,
        provenance_categories=(
            ArgumentSource.VERIFIED_ENTITY_RESOLUTION,
            ArgumentSource.EXECUTION_CONTEXT,
            ArgumentSource.EXECUTION_CONTEXT,
        ),
    )
    assert audit.provenance_categories == (
        ArgumentSource.EXECUTION_CONTEXT,
        ArgumentSource.VERIFIED_ENTITY_RESOLUTION,
    )
    with pytest.raises(ValidationError, match="non-negative"):
        audit.model_validate(
            {**audit.model_dump(), "protected_argument_count": -1}
        )


def test_concurrent_binder_usage_is_request_isolated() -> None:
    resolver = ResolverBehavior(value=resolved_result())
    instance = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(), resolver
    )

    def invoke(index: int):
        request = ArgumentBindingRequest(
            selection=ProviderToolSelection(
                tool_name="cancel_order",
                arguments={"order_number": "provider-%s" % index},
                call_id="call-%s" % index,
            ),
            trusted_values=TrustedExecutionValues(
                customer_id=CUSTOMER_ID, conversation_id=CONVERSATION_ID
            ),
            current_customer_message="cancel order %s" % index,
        )
        return instance.bind(request)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(invoke, range(40)))
    assert resolver.calls == 40
    assert {result.bound_selection.call_id for result in results} == {
        "call-%s" % index for index in range(40)
    }
    assert all(
        result.bound_selection.arguments == {"order_number": "ORD-10025"}
        for result in results
    )


def test_binding_package_has_no_forbidden_imports() -> None:
    package = Path(__file__).parents[2] / "app" / "argument_binding"
    forbidden = (
        "app.api",
        "app.authorization",
        "app.database",
        "app.harness",
        "app.providers",
        "app.services",
        "app.tools",
        "app.write_operations",
    )
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        assert not any(
            imported.startswith(prefix)
            for imported in imports
            for prefix in forbidden
        ), (path.name, imports)


def test_binding_package_runtime_import_boundary_in_clean_interpreter() -> None:
    backend = Path(__file__).parents[2]
    script = """
import json
import sys
import app.argument_binding
forbidden = (
    'app.tools', 'app.database', 'app.write_operations', 'app.authorization',
    'app.api', 'app.providers', 'app.services', 'app.harness',
    'app.entity_resolution.order_repository',
    'app.entity_resolution.order_resolver',
)
print(json.dumps(sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden)
)))
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(backend)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []
