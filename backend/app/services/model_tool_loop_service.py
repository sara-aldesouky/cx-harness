"""Provider-independent, bounded orchestration of model and approved tool turns."""

from __future__ import annotations

import logging
from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
from enum import Enum
from time import monotonic
from collections.abc import Iterable
from itertools import chain
from typing import Callable, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from app.config.settings import settings
from app.services.business_grounding_policy import BusinessGroundingPolicy
from app.services.orchestration_boundaries import (
    OrchestrationBoundaryValidator,
    OrchestrationBoundaryViolation,
    OrchestrationRuntimeLimits,
)
from app.services.orchestration_state import (
    OrchestrationCancellationToken,
    OrchestrationExecutionState,
)
from app.services.orchestration_trace import (
    OrchestrationExecutionTrace,
    OrchestrationTraceRecorder,
    ProviderResponseType,
    log_execution_trace,
)
from app.services.orchestration_runtime_gate import (
    OrchestrationRuntimeGate,
    orchestration_runtime_gate,
)
from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.harness.context_builder import ContextBuilder, MessageInput
from app.providers.base import ModelResponse, ModelToolLoopTurnResponse
from app.providers.registry import ProviderRegistry
from app.tools.context import ExecutionContext
from app.authentication import TrustedCustomerIdentity
from app.authorization import AuthorizationError, AuthorizationFailureCode
from app.role_policy import RolePolicyError, RolePolicyFailureCode
from app.tool_authorization import (
    ToolAuthorizationFailureCode,
    ToolAuthorizationPolicyError,
)
from app.data_protection import DataProtectionService, privacy_service
from app.security_audit import (
    AuditCategory,
    AuditResult,
    AuditSeverity,
    SecurityEventType,
    security_audit_recorder,
)
from app.tools.continuation_adapter import ProviderContinuationPayload
from app.tools.continuation_cycle import ToolContinuationCycle
from app.tools.selection import ToolSelectionResolver
from app.tools.selection import ToolSelectionRequest
from app.tools.selection_service import ToolSelectionResolutionError
from app.tools.result import ToolStatus
from app.tools.tool_runtime import ToolContinuationRuntime


logger = logging.getLogger(__name__)


class ModelToolLoopTermination(str, Enum):
    FINAL_RESPONSE = "final_response"
    MAX_TURNS_REACHED = "max_turns_reached"
    PROVIDER_ERROR = "provider_error"
    TOOL_ERROR = "tool_error"
    INVALID_TOOL_CALL = "invalid_tool_call"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    GROUNDING_REQUIRED = "grounding_required"
    TOOL_BUSINESS_FAILURE = "tool_business_failure"


class ModelToolLoopTurnRequest(BaseModel):
    """Immutable input for one provider turn, including all working context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str
    model_name: str
    context: ConversationContext
    tool_results: tuple[ProviderContinuationPayload, ...] = ()
    tool_call_history: tuple[ToolSelectionRequest, ...] = ()
    turn_number: int

    @field_validator("provider_name")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name must not be blank")
        return normalized

    @field_validator("model_name")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_name must not be blank")
        return normalized

    @field_validator("turn_number")
    @classmethod
    def validate_turn(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("turn_number must be positive")
        return value


class ModelToolLoopResult(BaseModel):
    """Immutable structured outcome, including partial progress on failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    final_response: Optional[ModelResponse]
    provider_name: str
    model_name: str
    provider_turns: int
    tools_executed: int
    completed: bool
    termination_reason: ModelToolLoopTermination
    tool_cycles: tuple[ToolContinuationCycle, ...] = ()
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    elapsed_ms: float


class ModelToolLoopConfigurationError(ValueError):
    """Raised when the bounded loop is constructed with unsafe configuration."""


class ModelToolLoopApplicationError(RuntimeError):
    """Application-safe failure carrying one explicit loop termination reason."""

    def __init__(self, result: ModelToolLoopResult) -> None:
        self.result = result
        super().__init__(result.error_message or "The model tool loop failed.")


class ModelToolLoopApplicationService:
    """Adapt the existing HTTP application boundary to the bounded loop."""

    def __init__(
        self,
        *,
        loop_factory: Optional[Callable[[], BoundedModelToolLoopService]] = None,
        provider_name: str = "ollama",
        model_name: str = settings.ollama_model_name,
        runtime_gate: OrchestrationRuntimeGate = orchestration_runtime_gate,
        data_protection: DataProtectionService = privacy_service,
    ) -> None:
        self._loop_factory = loop_factory
        self._provider_name = provider_name
        self._model_name = model_name
        if not isinstance(runtime_gate, OrchestrationRuntimeGate):
            raise TypeError("runtime_gate must be an OrchestrationRuntimeGate")
        self._runtime_gate = runtime_gate
        if not isinstance(data_protection, DataProtectionService):
            raise TypeError("data_protection must be a DataProtectionService")
        self._data_protection = data_protection

    def invoke(
        self,
        *,
        conversation_id: UUID,
        current_user_message: str,
        conversation_history: Iterable[MessageInput] = (),
        system_instructions: str,
        trusted_identity: TrustedCustomerIdentity,
    ):
        from app.harness.tool_loop_runtime import build_model_tool_loop
        from app.services.model_pipeline_service import (
            ModelPipelineServiceInputError,
            ModelPipelineServiceResult,
        )

        if not isinstance(conversation_id, UUID):
            raise ModelPipelineServiceInputError(
                "conversation_id must be a valid UUID"
            )
        if not isinstance(trusted_identity, TrustedCustomerIdentity):
            raise ModelPipelineServiceInputError(
                "trusted_identity must be authenticated"
            )
        protected_current = self._data_protection.protect_text(current_user_message)
        current = ConversationMessage(
            role=ConversationRole.USER,
            content=protected_current,
        )
        history_inputs = tuple(conversation_history)
        protected_history = tuple(
            self._data_protection.protect_message_input(message)
            for message in history_inputs
        )
        protected_instructions = self._data_protection.protect_text(
            system_instructions
        )
        if (
            protected_current != current_user_message
            or protected_instructions != system_instructions.strip()
            or any(
                protected != original
                for protected, original in zip(protected_history, history_inputs)
            )
        ):
            security_audit_recorder.record(
                SecurityEventType.PROMPT_SANITIZED,
                severity=AuditSeverity.INFO,
                result=AuditResult.SUCCESS,
                category=AuditCategory.PRIVACY,
                role=trusted_identity.role,
                correlation_id=conversation_id,
                customer_id=trusted_identity.customer_id,
            )
        context = ContextBuilder.build(
            system_instructions=protected_instructions,
            messages=chain(protected_history, (current,)),
            provider_name=self._provider_name,
            model_name=self._model_name,
        )
        factory = self._loop_factory or build_model_tool_loop
        trace_id = uuid4()
        loop = None
        with self._runtime_gate.execution(trace_id) as cancellation_token:
            try:
                loop = factory()
                result = loop.run(
                    provider_name=self._provider_name,
                    model_name=self._model_name,
                    context=context,
                    execution_context=ExecutionContext(
                        trace_id=trace_id,
                        execution_id=uuid4(),
                        conversation_id=conversation_id,
                        customer_id=trusted_identity.customer_id,
                        principal_role=trusted_identity.role.value,
                        model_name=self._model_name,
                    ),
                    cancellation_token=cancellation_token,
                )
            finally:
                close = getattr(loop, "close", None)
                if callable(close):
                    close()
        try:
            authorization_code = AuthorizationFailureCode(
                getattr(result, "error_code", None)
            )
        except (TypeError, ValueError):
            authorization_code = None
        if authorization_code is not None:
            raise AuthorizationError(
                authorization_code,
                result.error_message or "You do not have access to that resource.",
            )
        try:
            role_policy_code = RolePolicyFailureCode(
                getattr(result, "error_code", None)
            )
        except (TypeError, ValueError):
            role_policy_code = None
        if role_policy_code is not None:
            raise RolePolicyError(
                role_policy_code,
                result.error_message or "Your role does not permit this operation.",
            )
        try:
            tool_authorization_code = ToolAuthorizationFailureCode(
                getattr(result, "error_code", None)
            )
        except (TypeError, ValueError):
            tool_authorization_code = None
        if tool_authorization_code is not None:
            raise ToolAuthorizationPolicyError(
                tool_authorization_code,
                result.error_message or "This tool is not available to your role.",
            )
        if result.final_response is None:
            raise ModelToolLoopApplicationError(result)
        safe_content = self._data_protection.protect_text(
            result.final_response.content
        )
        if safe_content != result.final_response.content:
            security_audit_recorder.record(
                SecurityEventType.UNSAFE_OUTPUT_BLOCKED,
                severity=AuditSeverity.WARNING,
                result=AuditResult.SUCCESS,
                category=AuditCategory.PRIVACY,
                role=trusted_identity.role,
                correlation_id=conversation_id,
                customer_id=trusted_identity.customer_id,
            )
        return ModelPipelineServiceResult(
            content=safe_content,
            provider_name=result.provider_name,
            model_name=result.model_name,
        )
class BoundedModelToolLoopService:
    """Own a finite model/tool loop while delegating every specialist operation."""

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        selection_resolver: ToolSelectionResolver,
        tool_runtime: ToolContinuationRuntime,
        max_model_turns: int = settings.max_model_turns,
        timeout_seconds: Optional[float] = None,
        clock: Callable[[], float] = monotonic,
        grounding_policy: BusinessGroundingPolicy = BusinessGroundingPolicy(),
        state_factory: Callable[[UUID], OrchestrationExecutionState] = (
            OrchestrationExecutionState
        ),
        trace_sink: Callable[[OrchestrationExecutionTrace], None] = (
            log_execution_trace
        ),
        boundary_validator: Optional[OrchestrationBoundaryValidator] = None,
    ) -> None:
        if not isinstance(provider_registry, ProviderRegistry):
            raise TypeError("provider_registry must be a ProviderRegistry")
        if not isinstance(selection_resolver, ToolSelectionResolver):
            raise TypeError("selection_resolver must be a ToolSelectionResolver")
        if not isinstance(tool_runtime, ToolContinuationRuntime):
            raise TypeError("tool_runtime must be a ToolContinuationRuntime")
        if isinstance(max_model_turns, bool) or max_model_turns < 1:
            raise ModelToolLoopConfigurationError("max_model_turns must be positive")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ModelToolLoopConfigurationError("timeout_seconds must be positive")
        if not isinstance(grounding_policy, BusinessGroundingPolicy):
            raise TypeError("grounding_policy must be a BusinessGroundingPolicy")
        if not callable(state_factory):
            raise TypeError("state_factory must be callable")
        if not callable(trace_sink):
            raise TypeError("trace_sink must be callable")
        if boundary_validator is not None and not isinstance(
            boundary_validator, OrchestrationBoundaryValidator
        ):
            raise TypeError(
                "boundary_validator must be an OrchestrationBoundaryValidator"
            )
        self._providers = provider_registry
        self._resolver = selection_resolver
        self._runtime = tool_runtime
        self._max_turns = max_model_turns
        self._timeout = timeout_seconds
        self._clock = clock
        self._grounding_policy = grounding_policy
        self._state_factory = state_factory
        self._trace_sink = trace_sink
        self._boundaries = boundary_validator or OrchestrationBoundaryValidator(
            OrchestrationRuntimeLimits.from_settings(settings)
        )

    def close(self) -> None:
        """Release closeable provider resources without changing loop contracts."""

        for provider in self._providers.list():
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception(
                        "provider_cleanup_failed trace_id=%s conversation_id=%s "
                        "provider=%s model=%s provider_turn=%s tool_call_id=%s",
                        None,
                        None,
                        provider.provider_name,
                        provider.model_name,
                        None,
                        None,
                    )

    def run(
        self,
        *,
        provider_name: str,
        model_name: str,
        context: ConversationContext,
        execution_context: ExecutionContext,
        cancellation_token: Optional[OrchestrationCancellationToken] = None,
    ) -> ModelToolLoopResult:
        """Run one isolated lifecycle and always discard its temporary state."""

        if cancellation_token is not None and not isinstance(
            cancellation_token, OrchestrationCancellationToken
        ):
            raise TypeError(
                "cancellation_token must be an OrchestrationCancellationToken"
            )
        if not isinstance(execution_context, ExecutionContext):
            raise TypeError("execution_context must be an ExecutionContext")
        state = self._state_factory(execution_context.trace_id)
        trace = OrchestrationTraceRecorder(
            trace_id=execution_context.trace_id,
            conversation_id=execution_context.conversation_id,
            provider_name=provider_name,
            model_name=model_name,
        )
        try:
            result = self._run_bounded(
                provider_name=provider_name,
                model_name=model_name,
                context=context,
                execution_context=execution_context,
                cancellation_token=cancellation_token,
                state=state,
                trace=trace,
            )
            state.terminate(result.termination_reason.value)
            if result.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE:
                trace.final_response(result.provider_turns)
            trace.terminate(
                reason=result.termination_reason.value,
                completed=result.completed,
                error_summary=result.error_code,
            )
            return result
        except BaseException as error:
            trace.terminate(
                reason="orchestration_error",
                completed=False,
                error_summary=type(error).__name__,
            )
            raise
        finally:
            state.cleanup()
            trace.cleanup()
            completed_trace = trace.build()
            try:
                self._trace_sink(completed_trace)
            except Exception:
                logger.exception(
                    "orchestration_trace_sink_failed trace_id=%s "
                    "conversation_id=%s provider=%s model=%s provider_turn=%s "
                    "tool_call_id=%s",
                    execution_context.trace_id,
                    execution_context.conversation_id,
                    provider_name,
                    model_name,
                    None,
                    None,
                )

    def _run_bounded(
        self,
        *,
        provider_name: str,
        model_name: str,
        context: ConversationContext,
        execution_context: ExecutionContext,
        cancellation_token: Optional[OrchestrationCancellationToken],
        state: OrchestrationExecutionState,
        trace: OrchestrationTraceRecorder,
    ) -> ModelToolLoopResult:
        """Execute the established loop against one run-local state machine."""

        if not isinstance(context, ConversationContext):
            raise TypeError("context must be a ConversationContext")
        if not isinstance(execution_context, ExecutionContext):
            raise TypeError("execution_context must be an ExecutionContext")
        provider_key = provider_name.strip().lower()
        model_key = model_name.strip()
        provider = self._providers.get(provider_key)
        if provider.provider_name.strip().lower() != provider_key:
            raise ModelToolLoopConfigurationError("resolved provider identity mismatch")
        if provider.model_name != model_key:
            raise ModelToolLoopConfigurationError("resolved model identity mismatch")

        started = self._clock()
        messages = list(context.messages)
        cycles: list[ToolContinuationCycle] = []
        tool_call_history: list[ToolSelectionRequest] = []
        pending_results: tuple[ProviderContinuationPayload, ...] = ()
        seen_tool_fingerprints: set[str] = set()
        try:
            self._boundaries.validate_context(context)
        except OrchestrationBoundaryViolation as error:
            return self._safe_failure(
                provider_key,
                model_key,
                0,
                cycles,
                ModelToolLoopTermination.CANCELLED,
                started,
                error.code,
                error.public_message,
                trace_id=execution_context.trace_id,
            )
        for turn_number in range(1, self._max_turns + 1):
            if self._cancelled(cancellation_token):
                return self._result(provider_key, model_key, turn_number - 1, cycles,
                                    ModelToolLoopTermination.CANCELLED, started,
                                    "cancelled", "The model tool loop was cancelled.",
                                    trace_id=execution_context.trace_id)
            if self._timed_out(started):
                return self._result(provider_key, model_key, turn_number - 1, cycles,
                                    ModelToolLoopTermination.TIMEOUT, started,
                                    "loop_timeout", "The model tool loop timed out.",
                                    trace_id=execution_context.trace_id)
            working_context = ConversationContext(
                system_instructions=context.system_instructions,
                messages=tuple(messages),
                provider_name=provider_key,
                model_name=model_key,
            )
            try:
                self._boundaries.validate_provider_message_count(
                    len(working_context.messages)
                )
            except OrchestrationBoundaryViolation as error:
                return self._safe_failure(
                    provider_key,
                    model_key,
                    turn_number - 1,
                    cycles,
                    ModelToolLoopTermination.CANCELLED,
                    started,
                    error.code,
                    error.public_message,
                    trace_id=execution_context.trace_id,
                )
            request = ModelToolLoopTurnRequest(
                provider_name=provider_key,
                model_name=model_key,
                context=working_context,
                tool_results=pending_results,
                tool_call_history=tuple(tool_call_history),
                turn_number=turn_number,
            )
            state.begin_provider(turn_number)
            trace.provider_started(turn_number)
            try:
                turn = provider.run_tool_loop_turn(request)
            except TimeoutError:
                trace.provider_finished(
                    response_type=ProviderResponseType.ERROR,
                    success=False,
                    error_code="provider_timeout",
                    error_type="TimeoutError",
                )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.TIMEOUT, started,
                                    "provider_timeout", "The model provider timed out.",
                                    trace_id=execution_context.trace_id)
            except (
                KeyboardInterrupt,
                SystemExit,
                AsyncCancelledError,
                FutureCancelledError,
            ):
                trace.provider_finished(
                    response_type=ProviderResponseType.ERROR,
                    success=False,
                    error_code="provider_cancelled",
                    error_type="CancelledError",
                )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.CANCELLED, started,
                                    "provider_cancelled", "The model tool loop was cancelled.",
                                    trace_id=execution_context.trace_id)
            except Exception as error:
                trace.provider_finished(
                    response_type=ProviderResponseType.ERROR,
                    success=False,
                    error_code="provider_error",
                    error_type=type(error).__name__,
                )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.PROVIDER_ERROR, started,
                                    "provider_error", "The model provider failed.",
                                    trace_id=execution_context.trace_id)
            state.finish_provider()
            if self._cancelled(cancellation_token):
                trace.provider_finished(
                    response_type=ProviderResponseType.ERROR,
                    success=False,
                    error_code="provider_cancelled",
                    error_type="CooperativeCancellation",
                )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.CANCELLED, started,
                                    "provider_cancelled", "The model tool loop was cancelled.",
                                    trace_id=execution_context.trace_id)
            if self._timed_out(started):
                trace.provider_finished(
                    response_type=ProviderResponseType.ERROR,
                    success=False,
                    error_code="provider_timeout",
                    error_type="DeadlineExceeded",
                )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.TIMEOUT, started,
                                    "provider_timeout", "The model provider timed out.",
                                    trace_id=execution_context.trace_id)

            if not isinstance(turn, ModelToolLoopTurnResponse):
                trace.provider_finished(
                    response_type=ProviderResponseType.INVALID,
                    success=False,
                    error_code="invalid_provider_response",
                    error_type=type(turn).__name__,
                )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.PROVIDER_ERROR, started,
                                    "invalid_provider_response", "The model provider returned an invalid response.",
                                    trace_id=execution_context.trace_id)
            try:
                self._boundaries.validate_provider_response(turn)
            except OrchestrationBoundaryViolation as error:
                trace.provider_finished(
                    response_type=ProviderResponseType.INVALID,
                    success=False,
                    error_code=error.code,
                    error_type="OrchestrationBoundaryViolation",
                )
                return self._safe_failure(
                    provider_key,
                    model_key,
                    turn_number,
                    cycles,
                    ModelToolLoopTermination.PROVIDER_ERROR,
                    started,
                    error.code,
                    error.public_message,
                    trace_id=execution_context.trace_id,
                )
            if turn.final_response is not None:
                response = turn.final_response
                if response.provider_name.strip().lower() != provider_key or response.model_name != model_key:
                    trace.provider_finished(
                        response_type=ProviderResponseType.INVALID,
                        success=False,
                        error_code="provider_identity_mismatch",
                        error_type="ProviderIdentityMismatch",
                    )
                    return self._result(provider_key, model_key, turn_number, cycles,
                                        ModelToolLoopTermination.PROVIDER_ERROR, started,
                                        "provider_identity_mismatch", "The model response identity is invalid.",
                                        trace_id=execution_context.trace_id)
                trace.provider_finished(
                    response_type=ProviderResponseType.FINAL_RESPONSE,
                    success=True,
                )
                executed_tool_names = frozenset(
                    cycle.selection.tool_name
                    for cycle in cycles
                    if cycle.execution_outcome.status is ToolStatus.SUCCESS
                )
                if not self._grounding_policy.is_satisfied(
                    context, executed_tool_names
                ):
                    return self._safe_failure(
                        provider_key,
                        model_key,
                        turn_number,
                        cycles,
                        ModelToolLoopTermination.GROUNDING_REQUIRED,
                        started,
                        "grounding_required",
                        "I can’t verify that information without checking the approved customer-service tools.",
                        trace_id=execution_context.trace_id,
                    )
                return self._result(provider_key, model_key, turn_number, cycles,
                                    ModelToolLoopTermination.FINAL_RESPONSE, started,
                                    final_response=response,
                                    trace_id=execution_context.trace_id)

            trace.provider_finished(
                response_type=ProviderResponseType.TOOL_CALLS,
                tool_calls_requested=len(turn.tool_calls),
                success=True,
            )

            call_ids = ",".join(call.call_id for call in turn.tool_calls)
            assistant_metadata = (
                ("call_ids", call_ids),
                ("message_type", "tool_calls"),
            )
            if turn.assistant_content:
                messages.append(ConversationMessage(role=ConversationRole.ASSISTANT,
                                                    content=turn.assistant_content,
                                                    metadata=assistant_metadata))
            else:
                messages.append(ConversationMessage(
                    role=ConversationRole.ASSISTANT,
                    content=f"Requested {len(turn.tool_calls)} approved tool call(s).",
                    metadata=assistant_metadata,
                ))

            current_payloads: list[ProviderContinuationPayload] = []
            for tool_call in turn.tool_calls:
                if state.has_claimed(tool_call.call_id):
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.INVALID_TOOL_CALL, started,
                        "duplicate_tool_call",
                        "I couldn’t safely process the requested tool call. Please verify the information and try again.",
                        trace_id=execution_context.trace_id,
                    )
                fingerprint = self._boundaries.tool_call_fingerprint(tool_call)
                if fingerprint in seen_tool_fingerprints:
                    return self._safe_failure(
                        provider_key,
                        model_key,
                        turn_number,
                        cycles,
                        ModelToolLoopTermination.INVALID_TOOL_CALL,
                        started,
                        "repeated_tool_call",
                        "I couldn’t safely continue because the same tool request was repeated.",
                        trace_id=execution_context.trace_id,
                    )
                seen_tool_fingerprints.add(fingerprint)
                state.begin_tool(tool_call.call_id)
                tool_call_history.append(tool_call)
                try:
                    selection = self._resolver.resolve(tool_call)
                except Exception:
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.INVALID_TOOL_CALL, started,
                        "invalid_tool_call",
                        "I couldn’t validate the information needed for that request. Please check it and try again.",
                        trace_id=execution_context.trace_id,
                    )
                trace.tool_started(
                    provider_turn=turn_number,
                    tool_name=selection.tool_name,
                    tool_call_id=selection.call_id,
                )
                try:
                    cycle = self._runtime.cycle_service.run(
                        provider_key,
                        selection,
                        execution_context.model_copy(
                            update={"execution_id": uuid4()}
                        ),
                    )
                except TimeoutError:
                    trace.tool_finished(
                        success=False,
                        technical_error_type="TimeoutError",
                    )
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.TIMEOUT, started,
                        "tool_timeout",
                        "I’m unable to complete that check in time. Please try again.",
                        trace_id=execution_context.trace_id,
                    )
                except (
                    KeyboardInterrupt,
                    SystemExit,
                    AsyncCancelledError,
                    FutureCancelledError,
                ):
                    trace.tool_finished(
                        success=False,
                        technical_error_type="CancelledError",
                    )
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.CANCELLED, started,
                        "tool_cancelled",
                        "The request was cancelled before it could be completed.",
                        trace_id=execution_context.trace_id,
                    )
                except Exception as error:
                    trace.tool_finished(
                        success=False,
                        technical_error_type=type(error).__name__,
                    )
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.TOOL_ERROR, started,
                        "tool_error",
                        "I’m unable to check that information right now. Please try again later.",
                        trace_id=execution_context.trace_id,
                    )
                cycles.append(cycle)
                state.finish_tool()
                current_payloads.append(cycle.continuation_payload)
                outcome = cycle.execution_outcome
                try:
                    self._boundaries.validate_tool_result(outcome)
                except OrchestrationBoundaryViolation as error:
                    trace.tool_finished(
                        success=False,
                        technical_error_type="OrchestrationBoundaryViolation",
                    )
                    return self._safe_failure(
                        provider_key,
                        model_key,
                        turn_number,
                        cycles,
                        ModelToolLoopTermination.TOOL_ERROR,
                        started,
                        error.code,
                        error.public_message,
                        trace_id=execution_context.trace_id,
                    )
                trace.tool_finished(
                    success=outcome.error is None,
                    business_failure_code=(
                        outcome.error.error_code
                        if outcome.error is not None
                        else None
                    ),
                )
                tool_content = outcome.model_dump_json()
                messages.append(ConversationMessage(
                    role=ConversationRole.TOOL,
                    content=tool_content,
                    metadata=(("call_id", outcome.call_id), ("tool_name", outcome.tool_name)),
                ))
                if self._cancelled(cancellation_token):
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.CANCELLED, started,
                        "tool_cancelled",
                        "The request was cancelled before it could be completed.",
                        trace_id=execution_context.trace_id,
                    )
                if self._timed_out(started):
                    return self._safe_failure(
                        provider_key, model_key, turn_number, cycles,
                        ModelToolLoopTermination.TIMEOUT, started,
                        "tool_timeout",
                        "I’m unable to complete that check in time. Please try again.",
                        trace_id=execution_context.trace_id,
                    )
                if outcome.error is not None:
                    return self._safe_failure(
                        provider_key,
                        model_key,
                        turn_number,
                        cycles,
                        ModelToolLoopTermination.TOOL_BUSINESS_FAILURE,
                        started,
                        outcome.error.error_code,
                        outcome.error.public_message,
                        trace_id=execution_context.trace_id,
                    )
            pending_results = tuple(current_payloads)

        return self._safe_failure(
            provider_key,
            model_key,
            self._max_turns,
            cycles,
            ModelToolLoopTermination.MAX_TURNS_REACHED,
            started,
            "max_turns_reached",
            "I couldn’t complete the request within the safe turn limit.",
            trace_id=execution_context.trace_id,
        )

    def _timed_out(self, started: float) -> bool:
        return self._timeout is not None and self._clock() - started >= self._timeout

    @staticmethod
    def _cancelled(
        cancellation_token: Optional[OrchestrationCancellationToken],
    ) -> bool:
        return cancellation_token is not None and cancellation_token.is_cancelled

    def _result(
        self, provider_name: str, model_name: str, turns: int,
        cycles: list[ToolContinuationCycle], reason: ModelToolLoopTermination,
        started: float, error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        final_response: Optional[ModelResponse] = None,
        trace_id: Optional[UUID] = None,
    ) -> ModelToolLoopResult:
        completed = reason is ModelToolLoopTermination.FINAL_RESPONSE
        result = ModelToolLoopResult(
            final_response=final_response,
            provider_name=provider_name,
            model_name=model_name,
            provider_turns=turns,
            tools_executed=len(cycles),
            completed=completed,
            termination_reason=reason,
            tool_cycles=tuple(cycles),
            error_code=error_code,
            error_message=error_message,
            elapsed_ms=max(0.0, (self._clock() - started) * 1000),
        )
        return result

    def _safe_failure(
        self,
        provider_name: str,
        model_name: str,
        turns: int,
        cycles: list[ToolContinuationCycle],
        reason: ModelToolLoopTermination,
        started: float,
        error_code: str,
        message: str,
        trace_id: Optional[UUID] = None,
    ) -> ModelToolLoopResult:
        return self._result(
            provider_name,
            model_name,
            turns,
            cycles,
            reason,
            started,
            error_code,
            message,
            final_response=ModelResponse(
                content=message,
                provider_name=provider_name,
                model_name=model_name,
            ),
            trace_id=trace_id,
        )
