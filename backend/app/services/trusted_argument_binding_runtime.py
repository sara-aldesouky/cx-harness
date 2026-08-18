"""Stage 13.4 production boundary: trusted binding before schema validation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Mapping, Optional

from app.argument_binding import (
    ArgumentBindingPolicy,
    ArgumentBindingPolicyRegistry,
    ArgumentBindingRequest,
    ArgumentBindingResult,
    ArgumentSource,
    BindingAuditMetadata,
    BindingFailure,
    BindingStatus,
    ModelValueBehavior,
    ProviderToolSelection,
    ToolBindingPolicy,
    TrustedArgumentBinder,
    TrustedExecutionValues,
    UnknownArgumentBehavior,
    PolicySchemaCompatibilityValidator,
    RegisteredToolSchema,
    RegistryCompletenessValidator,
    ToolSchemaArgument,
    write_tool_binding_policies,
)
from app.conversation_state import (
    ConversationState,
    ConversationStateExpiredError,
    ConversationStateService,
    StateStatus,
)
from app.entity_resolution import OrderEntityResolver
from app.entity_resolution.contracts import EntityResolutionRequest, ResolutionStatus
from app.conversation_continuity import (
    ContinuityFailureCategory,
    TrustedContinuityError,
    TrustedConversationEntityContinuityService,
    TrustedContinuityBindingContext,
)
from app.tools.context import ExecutionContext
from app.tools.registry import ToolRegistry
from app.tools.selection import (
    ToolSelectionRequest,
    ToolSelectionResolver,
    ValidatedToolSelection,
)


class TrustedSelectionRuntimeError(RuntimeError):
    """Base error for the Stage 13.4 integration boundary."""


class InvalidTrustedSelectionRuntimeInputError(TrustedSelectionRuntimeError, TypeError):
    """Raised when the integration boundary lacks trusted typed input."""


class TrustedArgumentBindingRejected(TrustedSelectionRuntimeError):
    """Carry one safe structured binder rejection without fallback execution."""

    def __init__(self, result: ArgumentBindingResult) -> None:
        self.result = result
        message = (
            result.failure.public_message
            if result.failure is not None
            else "The requested operation could not be prepared safely."
        )
        super().__init__(message)


class TrustedSelectionPipeline:
    """Invoke the frozen binder once, then validate only its bound arguments."""

    def __init__(
        self,
        binder: TrustedArgumentBinder,
        schema_resolver: ToolSelectionResolver,
        *,
        conversation_state_service: Optional[ConversationStateService] = None,
        state_required_tools: Iterable[str] = (),
        clock: Optional[Callable[[], datetime]] = None,
        continuity_service: Optional[
            TrustedConversationEntityContinuityService
        ] = None,
        continuity_order_resolver: Optional[OrderEntityResolver] = None,
        continuity_read_order_tools: Iterable[str] = (),
        continuity_read_order_arguments: Optional[Mapping[str, str]] = None,
    ) -> None:
        if not isinstance(binder, TrustedArgumentBinder):
            raise TypeError("binder must be a TrustedArgumentBinder")
        if not isinstance(schema_resolver, ToolSelectionResolver):
            raise TypeError("schema_resolver must be a ToolSelectionResolver")
        if conversation_state_service is not None and not isinstance(
            conversation_state_service, ConversationStateService
        ):
            raise TypeError(
                "conversation_state_service must be a ConversationStateService"
            )
        self._binder = binder
        self._schema_resolver = schema_resolver
        self._state = conversation_state_service
        normalized_required_tools = frozenset(
            name.strip() for name in state_required_tools
        )
        if any(not name for name in normalized_required_tools):
            raise ValueError("state-required tool names must be non-empty")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._state_required_tools = normalized_required_tools
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if continuity_service is not None and not isinstance(
            continuity_service, TrustedConversationEntityContinuityService
        ):
            raise TypeError(
                "continuity_service must be a TrustedConversationEntityContinuityService"
            )
        self._continuity = continuity_service
        if continuity_order_resolver is not None and not isinstance(
            continuity_order_resolver, OrderEntityResolver
        ):
            raise TypeError("continuity_order_resolver must be an OrderEntityResolver")
        self._continuity_order_resolver = continuity_order_resolver
        self._continuity_read_order_tools = frozenset(
            name.strip() for name in continuity_read_order_tools
        )
        if any(not name for name in self._continuity_read_order_tools):
            raise ValueError("continuity read-tool names must be non-empty")
        self._continuity_read_order_arguments = dict(
            continuity_read_order_arguments or ()
        )

    def bind_and_validate(
        self,
        selection: ToolSelectionRequest,
        execution_context: ExecutionContext,
        current_customer_message: str,
        *,
        source_turn: int = 1,
    ) -> ValidatedToolSelection:
        """Return one schema-validated selection derived only from bound data."""

        if not isinstance(selection, ToolSelectionRequest):
            raise InvalidTrustedSelectionRuntimeInputError(
                "selection must be a ToolSelectionRequest"
            )
        if not isinstance(execution_context, ExecutionContext):
            raise InvalidTrustedSelectionRuntimeInputError(
                "execution_context must be an ExecutionContext"
            )
        if execution_context.customer_id is None:
            raise InvalidTrustedSelectionRuntimeInputError(
                "trusted customer identity is required"
            )
        if execution_context.conversation_id is None:
            raise InvalidTrustedSelectionRuntimeInputError(
                "trusted conversation identity is required"
            )
        if not isinstance(current_customer_message, str) or not current_customer_message.strip():
            raise InvalidTrustedSelectionRuntimeInputError(
                "current_customer_message must be non-empty"
            )

        binding_message = current_customer_message
        effective_selection = selection
        if self._continuity is not None:
            try:
                prepared = self._continuity.prepare_binding(
                    selection,
                    execution_context,
                    current_customer_message,
                    source_turn,
                )
            except TrustedContinuityError as error:
                status = (
                    ResolutionStatus.EXPIRED
                    if error.category is ContinuityFailureCategory.STALE_ENTITY
                    else ResolutionStatus.FORBIDDEN
                    if error.category
                    in {
                        ContinuityFailureCategory.CUSTOMER_MISMATCH,
                        ContinuityFailureCategory.CONVERSATION_MISMATCH,
                    }
                    else ResolutionStatus.CLARIFICATION_REQUIRED
                )
                self._reject_state(
                    error.category.value,
                    error.public_message,
                    status,
                )
            state = prepared.conversation_state
            binding_message = prepared.resolver_message
            effective_selection = self._bind_read_order_reference(
                selection,
                execution_context,
                prepared,
            )
        else:
            state = self._load_state(
                selection.tool_name, execution_context.conversation_id
            )

        binding_result = self._binder.bind(
            ArgumentBindingRequest(
                selection=ProviderToolSelection(
                    tool_name=effective_selection.tool_name,
                    arguments=effective_selection.arguments,
                    call_id=effective_selection.call_id,
                ),
                trusted_values=TrustedExecutionValues(
                    customer_id=execution_context.customer_id,
                    conversation_id=execution_context.conversation_id,
                ),
                current_customer_message=binding_message,
                conversation_state=state,
            )
        )
        if binding_result.bound_selection is None:
            raise TrustedArgumentBindingRejected(binding_result)

        bound = binding_result.bound_selection
        return self._schema_resolver.resolve(
            ToolSelectionRequest(
                call_id=bound.call_id or selection.call_id,
                tool_name=bound.tool_name,
                tool_version=selection.tool_version,
                arguments=bound.arguments,
            )
        )

    def _bind_read_order_reference(
        self,
        selection: ToolSelectionRequest,
        execution_context: ExecutionContext,
        prepared: TrustedContinuityBindingContext,
    ) -> ToolSelectionRequest:
        """Repair only masked/missing read identifiers using verified continuity."""

        if selection.tool_name not in self._continuity_read_order_tools:
            return selection
        order_key = next(
            (name for name in ("order_number", "order_id") if name in selection.arguments),
            None,
        )
        supplied = selection.arguments.get(order_key) if order_key else None
        needs_binding = (
            order_key is None
            or not isinstance(supplied, str)
            or "*" in supplied
            or prepared.audit.entity_reused
        )
        if not needs_binding:
            return selection
        if self._continuity_order_resolver is None:
            self._reject_state(
                "order_resolution_unavailable",
                "Order information is temporarily unavailable.",
                ResolutionStatus.STALE,
            )
        result = self._continuity_order_resolver.resolve(
            EntityResolutionRequest(
                trusted_customer_id=execution_context.customer_id,
                conversation_id=execution_context.conversation_id,
                customer_message=prepared.resolver_message,
                conversation_state=prepared.conversation_state,
            )
        )
        if result.status is not ResolutionStatus.RESOLVED or result.resolved_entity is None:
            self._reject_state(
                result.error_code or "order_resolution_failed",
                result.public_message,
                result.status,
            )
        target_key = self._continuity_read_order_arguments.get(
            selection.tool_name, order_key or "order_number"
        )
        arguments = {
            key: value
            for key, value in selection.arguments.items()
            if key not in {"order_number", "order_id"}
        }
        arguments[target_key] = result.resolved_entity.public_reference
        return ToolSelectionRequest(
            call_id=selection.call_id,
            tool_name=selection.tool_name,
            tool_version=selection.tool_version,
            arguments=arguments,
        )

    def _load_state(
        self, tool_name: str, conversation_id
    ) -> Optional[ConversationState]:
        """Load optional state and fail closed when a declared dependency is absent."""

        required = tool_name in self._state_required_tools
        if self._state is None:
            if required:
                self._reject_state(
                    "conversation_state_required",
                    "The conversation context required for this request is unavailable.",
                    ResolutionStatus.NOT_FOUND,
                )
            return None
        try:
            state = self._state.load(conversation_id)
        except ConversationStateExpiredError:
            if required:
                self._reject_state(
                    "conversation_state_expired",
                    "The conversation context has expired. Please provide the details again.",
                    ResolutionStatus.EXPIRED,
                )
            return None
        except Exception:
            if required:
                self._reject_state(
                    "conversation_state_unavailable",
                    "The conversation context is temporarily unavailable.",
                    ResolutionStatus.STALE,
                )
            return None

        if state is None:
            if required:
                self._reject_state(
                    "conversation_state_required",
                    "The conversation context required for this request is unavailable.",
                    ResolutionStatus.NOT_FOUND,
                )
            return None
        if not isinstance(state, ConversationState):
            if required:
                self._reject_state(
                    "conversation_state_invalid",
                    "The conversation context could not be verified.",
                    ResolutionStatus.INVALID_REFERENCE,
                )
            return None
        if state.metadata.conversation_id != conversation_id:
            if required:
                self._reject_state(
                    "conversation_state_forbidden",
                    "The conversation context could not be verified.",
                    ResolutionStatus.FORBIDDEN,
                )
            return None

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise TrustedSelectionRuntimeError("runtime clock must return UTC time")
        now = now.astimezone(timezone.utc)
        if (
            state.metadata.status is StateStatus.EXPIRED
            or state.metadata.expires_at <= now
        ):
            if required:
                self._reject_state(
                    "conversation_state_expired",
                    "The conversation context has expired. Please provide the details again.",
                    ResolutionStatus.EXPIRED,
                )
            return None
        if state.metadata.status is not StateStatus.ACTIVE:
            if required:
                self._reject_state(
                    "conversation_state_stale",
                    "The conversation context could not be verified.",
                    ResolutionStatus.STALE,
                )
            return None
        return state

    @staticmethod
    def _reject_state(
        code: str,
        public_message: str,
        resolution_status: ResolutionStatus,
    ) -> None:
        raise TrustedArgumentBindingRejected(
            ArgumentBindingResult(
                status=BindingStatus.RESOLUTION_FAILED,
                failure=BindingFailure(
                    code=code,
                    public_message=public_message,
                    resolution_status=resolution_status,
                ),
                audit_metadata=BindingAuditMetadata(
                    binding_status=BindingStatus.RESOLUTION_FAILED,
                    protected_argument_count=0,
                    injected_argument_count=0,
                    replaced_argument_count=0,
                    resolver_outcome=resolution_status,
                ),
            )
        )


def build_runtime_binding_policy_registry(
    tool_registry: ToolRegistry,
) -> ArgumentBindingPolicyRegistry:
    """Compose frozen write policies with schema-derived pass-through policies."""

    if not isinstance(tool_registry, ToolRegistry):
        raise TypeError("tool_registry must be a ToolRegistry")
    registry = ArgumentBindingPolicyRegistry()
    protected = {policy.tool_name: policy for policy in write_tool_binding_policies()}
    for tool_class in tool_registry.list():
        policy = protected.get(tool_class.metadata.name)
        if policy is None:
            requirements = tuple(
                ArgumentBindingPolicy(
                    argument_name=name,
                    required=field.is_required(),
                    protected=False,
                    permitted_sources=(ArgumentSource.MODEL_SUGGESTED,),
                    model_value_behavior=ModelValueBehavior.ALLOW,
                )
                for name, field in tool_class.input_schema.model_fields.items()
            )
            policy = ToolBindingPolicy(
                tool_name=tool_class.metadata.name,
                argument_policies=requirements,
                unknown_argument_behavior=UnknownArgumentBehavior.REJECT,
                requires_order_resolution=False,
            )
        registry.register(policy)
    return registry


def validate_runtime_binding_configuration(
    tool_registry: ToolRegistry,
    policy_registry: ArgumentBindingPolicyRegistry,
) -> None:
    """Validate schema-derived descriptors before the runtime serves traffic."""

    if not isinstance(tool_registry, ToolRegistry):
        raise TypeError("tool_registry must be a ToolRegistry")
    if not isinstance(policy_registry, ArgumentBindingPolicyRegistry):
        raise TypeError("policy_registry must be an ArgumentBindingPolicyRegistry")
    compatibility = PolicySchemaCompatibilityValidator()
    write_registry = ArgumentBindingPolicyRegistry()
    write_descriptors = []
    for tool_class in tool_registry.list():
        policy = policy_registry.get(tool_class.metadata.name)
        protected_names = {
            requirement.argument_name
            for requirement in policy.argument_policies
            if requirement.protected and requirement.include_in_tool_arguments
        }
        descriptor = RegisteredToolSchema(
            tool_name=tool_class.metadata.name,
            arguments=tuple(
                ToolSchemaArgument(
                    name=name,
                    required=field.is_required(),
                    protected=name in protected_names,
                )
                for name, field in tool_class.input_schema.model_fields.items()
            ),
            executable=tool_class.metadata.is_enabled,
            write_operation=not tool_class.metadata.is_read_only,
        )
        compatibility.validate(policy, descriptor)
        if descriptor.executable and descriptor.write_operation:
            write_registry.register(policy)
            write_descriptors.append(descriptor)
    RegistryCompletenessValidator(compatibility).validate(
        write_registry, tuple(write_descriptors)
    )
