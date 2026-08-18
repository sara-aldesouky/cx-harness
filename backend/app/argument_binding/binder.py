"""Isolated trusted argument binder; it never resolves entities itself."""

from __future__ import annotations

from collections.abc import Iterable
from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
from typing import Protocol, runtime_checkable

from app.argument_binding.contracts import (
    ArgumentBindingRequest,
    ArgumentBindingResult,
    BindingAuditMetadata,
    ArgumentProvenance,
    ArgumentSource,
    BindingFailure,
    BindingStatus,
    BoundArgument,
    BoundToolSelectionRequest,
    ModelValueBehavior,
    UnknownArgumentBehavior,
)
from app.argument_binding.registry import ArgumentBindingPolicyRegistry
from app.entity_resolution.contracts import (
    EntityResolutionRequest,
    EntityResolutionResult,
    ResolutionRequirement,
    ResolutionStatus,
)
from app.argument_binding._immutable_json import json_copy


@runtime_checkable
class OrderResolutionService(Protocol):
    def resolve(self, request: EntityResolutionRequest) -> EntityResolutionResult: ...


_RESOLUTION_STATUS_MAP = {
    ResolutionStatus.CLARIFICATION_REQUIRED: BindingStatus.CLARIFICATION_REQUIRED,
    ResolutionStatus.NOT_FOUND: BindingStatus.RESOLUTION_FAILED,
    ResolutionStatus.FORBIDDEN: BindingStatus.UNTRUSTED_ARGUMENT,
    ResolutionStatus.INVALID_REFERENCE: BindingStatus.UNTRUSTED_ARGUMENT,
    ResolutionStatus.EXPIRED: BindingStatus.RESOLUTION_FAILED,
    ResolutionStatus.STALE: BindingStatus.RESOLUTION_FAILED,
}


class TrustedArgumentBinder:
    def __init__(
        self,
        policy_registry: ArgumentBindingPolicyRegistry,
        order_resolver: OrderResolutionService,
        *,
        known_tool_names: Iterable[str] = (),
    ) -> None:
        if not isinstance(policy_registry, ArgumentBindingPolicyRegistry):
            raise TypeError("policy_registry must be an ArgumentBindingPolicyRegistry")
        if not isinstance(order_resolver, OrderResolutionService):
            raise TypeError("order_resolver must implement OrderResolutionService")
        self._policies = policy_registry
        listed = {policy.tool_name for policy in policy_registry.list_policies()}
        self._known_tools = frozenset(listed | {name.strip() for name in known_tool_names})
        self._order_resolver = order_resolver

    def bind(self, request: ArgumentBindingRequest) -> ArgumentBindingResult:
        if not isinstance(request, ArgumentBindingRequest):
            raise TypeError("request must be an ArgumentBindingRequest")
        tool_name = request.selection.tool_name
        if tool_name not in self._known_tools:
            return self._failure(BindingStatus.INVALID_TOOL, "invalid_tool", "The requested tool is unavailable.")
        if not self._policies.contains(tool_name):
            return self._failure(BindingStatus.POLICY_NOT_FOUND, "policy_not_found", "The requested tool is unavailable.")
        policy = self._policies.get(tool_name)
        provider_arguments = json_copy(request.selection.arguments)
        policy_names = {item.argument_name for item in policy.argument_policies}
        unexpected = set(provider_arguments) - policy_names
        if unexpected and policy.unknown_argument_behavior is UnknownArgumentBehavior.REJECT:
            return self._failure(
                BindingStatus.UNTRUSTED_ARGUMENT,
                "unexpected_argument",
                "The requested arguments are not supported.",
                protected_count=sum(item.protected for item in policy.argument_policies),
            )

        resolution = None
        if policy.requires_order_resolution:
            resolution_request = EntityResolutionRequest(
                trusted_customer_id=request.trusted_values.customer_id,
                conversation_id=request.trusted_values.conversation_id,
                customer_message=request.current_customer_message,
                requirement=ResolutionRequirement(
                    allow_unique_active_order=request.allow_unique_active_order,
                    allow_latest_order=request.allow_latest_order,
                ),
                conversation_state=request.conversation_state,
            )
            try:
                resolution = self._order_resolver.resolve(resolution_request)
            except TimeoutError:
                return self._resolver_contract_failure("resolver_timeout", policy)
            except AsyncCancelledError:
                raise
            except FutureCancelledError:
                return self._resolver_contract_failure("resolver_cancelled", policy)
            except Exception:
                return self._resolver_contract_failure("resolver_unavailable", policy)
            if not isinstance(resolution, EntityResolutionResult):
                return self._resolver_contract_failure("invalid_resolver_response", policy)
            if not isinstance(resolution.status, ResolutionStatus):
                return self._resolver_contract_failure("invalid_resolver_contract", policy)
            try:
                resolution = EntityResolutionResult.model_validate(
                    resolution.model_dump()
                )
            except Exception:
                return self._resolver_contract_failure("invalid_resolver_contract", policy)
            if resolution.status is not ResolutionStatus.RESOLVED:
                return self._resolution_failure(resolution, policy)

        bound = []
        tool_arguments = {}
        applicable_requirements = tuple(
            requirement
            for requirement in policy.argument_policies
            if requirement.required
            or requirement.protected
            or requirement.argument_name in provider_arguments
        )
        for requirement in applicable_requirements:
            provided = requirement.argument_name in provider_arguments
            if requirement.resolution_key == "order":
                assert resolution is not None and resolution.resolved_entity is not None
                value = resolution.resolved_entity.public_reference
                source = ArgumentSource.VERIFIED_ENTITY_RESOLUTION
            elif requirement.argument_name == "customer_id":
                value = request.trusted_values.customer_id
                source = ArgumentSource.EXECUTION_CONTEXT
            elif requirement.argument_name == "conversation_id":
                value = request.trusted_values.conversation_id
                source = ArgumentSource.EXECUTION_CONTEXT
            elif provided and requirement.model_value_behavior is ModelValueBehavior.ALLOW:
                value = provider_arguments[requirement.argument_name]
                source = ArgumentSource.MODEL_SUGGESTED
            else:
                return self._failure(
                    BindingStatus.MISSING_REQUIRED_ARGUMENT,
                    "missing_required_argument",
                    "A required argument is missing.",
                    resolution_result=resolution,
                    protected_count=sum(
                        item.protected for item in policy.argument_policies
                    ),
                )
            provenance = ArgumentProvenance(
                source=source,
                protected=requirement.protected,
                replaced_model_value=provided and requirement.protected,
                injected=not provided,
            )
            argument = BoundArgument(
                argument_name=requirement.argument_name,
                value=value,
                provenance=provenance,
                included_in_tool_arguments=requirement.include_in_tool_arguments,
            )
            bound.append(argument)
            if requirement.include_in_tool_arguments:
                tool_arguments[requirement.argument_name] = value

        selection = BoundToolSelectionRequest(
            tool_name=tool_name,
            arguments=tool_arguments,
            bound_arguments=tuple(bound),
            trusted_execution_values=request.trusted_values,
            call_id=request.selection.call_id,
            safe_source_metadata=request.selection.safe_source_metadata,
        )
        injected = sum(item.provenance.injected for item in bound)
        replaced = sum(item.provenance.replaced_model_value for item in bound)
        status = BindingStatus.BOUND if injected or replaced or resolution is not None else BindingStatus.UNCHANGED
        return ArgumentBindingResult(
            status=status,
            bound_selection=selection,
            resolution_result=resolution,
            injected_count=injected,
            replaced_count=replaced,
            audit_metadata=BindingAuditMetadata(
                binding_status=status,
                protected_argument_count=sum(item.provenance.protected for item in bound),
                injected_argument_count=injected,
                replaced_argument_count=replaced,
                provenance_categories=tuple(item.provenance.source for item in bound),
                resolver_outcome=(resolution.status if resolution is not None else None),
            ),
        )

    @staticmethod
    def _resolution_failure(result: EntityResolutionResult, policy) -> ArgumentBindingResult:
        status = _RESOLUTION_STATUS_MAP[result.status]
        if result.status is ResolutionStatus.CLARIFICATION_REQUIRED and len(result.candidates) > 1:
            status = BindingStatus.AMBIGUOUS_ENTITY
        return TrustedArgumentBinder._failure(
            status,
            result.error_code or "resolution_failed",
            result.public_message,
            resolution_result=result,
            protected_count=sum(item.protected for item in policy.argument_policies),
        )

    @staticmethod
    def _resolver_contract_failure(code: str, policy) -> ArgumentBindingResult:
        return TrustedArgumentBinder._failure(
            BindingStatus.RESOLUTION_FAILED,
            code,
            "Order resolution is temporarily unavailable.",
            protected_count=sum(item.protected for item in policy.argument_policies),
        )

    @staticmethod
    def _failure(
        status,
        code,
        message,
        *,
        resolution_result=None,
        protected_count=0,
    ) -> ArgumentBindingResult:
        return ArgumentBindingResult(
            status=status,
            failure=BindingFailure(
                code=code,
                public_message=message,
                resolution_status=(resolution_result.status if resolution_result else None),
            ),
            resolution_result=resolution_result,
            audit_metadata=BindingAuditMetadata(
                binding_status=status,
                protected_argument_count=protected_count,
                injected_argument_count=0,
                replaced_argument_count=0,
                provenance_categories=(),
                resolver_outcome=(
                    resolution_result.status if resolution_result is not None else None
                ),
            ),
        )
