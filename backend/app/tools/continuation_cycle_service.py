"""Synchronous orchestration of exactly one completed tool-continuation cycle."""

from __future__ import annotations

from concurrent.futures import CancelledError as FutureCancelledError
from typing import Callable, Optional

from app.tools.context import ExecutionContext
from app.tools.continuation_cycle import (
    ToolContinuationCycle,
    ToolContinuationCycleFactory,
)
from app.tools.continuation_service import ProviderContinuationService
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_outcome import ToolExecutionOutcomeFactory
from app.tools.execution_request import ToolExecutionRequestFactory
from app.tools.selection import ValidatedToolSelection


class SingleToolContinuationCycleServiceError(Exception):
    """Base error for single-cycle orchestration failures."""


class InvalidToolContinuationCycleServiceInputError(
    SingleToolContinuationCycleServiceError, TypeError
):
    """Raised when orchestration does not start from trusted typed inputs."""


class ToolExecutionRequestCreationError(SingleToolContinuationCycleServiceError):
    """Raised when the execution-request stage fails."""


class ToolCycleExecutionError(SingleToolContinuationCycleServiceError):
    """Raised when gateway or executor processing fails unexpectedly."""


class ToolExecutionOutcomeCreationError(SingleToolContinuationCycleServiceError):
    """Raised when result-to-outcome correlation fails."""


class ToolContinuationTranslationError(SingleToolContinuationCycleServiceError):
    """Raised when continuation lookup or translation fails."""


class ToolContinuationCycleCreationError(SingleToolContinuationCycleServiceError):
    """Raised when final cycle consistency validation fails."""


class SingleToolContinuationCycleService:
    """Coordinate existing boundaries for one already-validated selection.

    This service guarantees ordered, exactly-once delegation without retries.
    It does not provide transactional rollback, compensation, idempotency, model
    invocation, provider-output translation, or multi-tool orchestration.
    """

    def __init__(
        self,
        execution_request_factory: ToolExecutionRequestFactory,
        execution_gateway: SingleToolExecutionGateway,
        execution_outcome_factory: ToolExecutionOutcomeFactory,
        continuation_service: ProviderContinuationService,
        cycle_factory: ToolContinuationCycleFactory,
        completion_observer: Optional[Callable[..., None]] = None,
    ) -> None:
        dependencies = (
            (
                "execution_request_factory",
                execution_request_factory,
                ToolExecutionRequestFactory,
            ),
            ("execution_gateway", execution_gateway, SingleToolExecutionGateway),
            (
                "execution_outcome_factory",
                execution_outcome_factory,
                ToolExecutionOutcomeFactory,
            ),
            (
                "continuation_service",
                continuation_service,
                ProviderContinuationService,
            ),
            ("cycle_factory", cycle_factory, ToolContinuationCycleFactory),
        )
        for name, dependency, expected in dependencies:
            if not isinstance(dependency, expected):
                raise TypeError(f"{name} must be a {expected.__name__}")

        self._execution_request_factory = execution_request_factory
        self._execution_gateway = execution_gateway
        self._execution_outcome_factory = execution_outcome_factory
        self._continuation_service = continuation_service
        self._cycle_factory = cycle_factory
        if completion_observer is not None and not callable(completion_observer):
            raise TypeError("completion_observer must be callable")
        self._completion_observer = completion_observer

    def run(
        self,
        provider_name: str,
        selection: ValidatedToolSelection,
        context: ExecutionContext,
        *,
        source_turn: int = 1,
    ) -> ToolContinuationCycle:
        """Process one selection in lifecycle order and return one complete cycle."""

        if not isinstance(provider_name, str) or not provider_name.strip():
            raise InvalidToolContinuationCycleServiceInputError(
                "provider_name must be a non-empty string"
            )
        if not isinstance(selection, ValidatedToolSelection):
            raise InvalidToolContinuationCycleServiceInputError(
                "selection must be a ValidatedToolSelection"
            )
        if not isinstance(context, ExecutionContext):
            raise InvalidToolContinuationCycleServiceInputError(
                "context must be a trusted ExecutionContext"
            )
        if isinstance(source_turn, bool) or source_turn < 1:
            raise InvalidToolContinuationCycleServiceInputError(
                "source_turn must be positive"
            )

        safe_context = (
            f"provider {provider_name.strip().lower()!r}, "
            f"call ID {selection.call_id!r}, tool {selection.tool_name!r} "
            f"version {selection.tool_version!r}"
        )

        try:
            request = self._execution_request_factory.create(selection, context)
        except Exception as error:
            raise ToolExecutionRequestCreationError(
                f"execution-request creation failed for {safe_context}"
            ) from error

        try:
            result = self._execution_gateway.execute(request)
        except (TimeoutError, FutureCancelledError):
            raise
        except Exception as error:
            raise ToolCycleExecutionError(
                f"tool execution failed for {safe_context}"
            ) from error

        try:
            outcome = self._execution_outcome_factory.create(request, result)
        except Exception as error:
            raise ToolExecutionOutcomeCreationError(
                f"execution-outcome creation failed for {safe_context}"
            ) from error

        try:
            payload = self._continuation_service.translate(provider_name, outcome)
        except Exception as error:
            raise ToolContinuationTranslationError(
                f"continuation translation failed for {safe_context}"
            ) from error

        try:
            cycle = self._cycle_factory.create(
                provider_name,
                selection,
                request,
                outcome,
                payload,
            )
        except Exception as error:
            raise ToolContinuationCycleCreationError(
                f"continuation-cycle creation failed for {safe_context}"
            ) from error
        if self._completion_observer is not None:
            try:
                self._completion_observer(request, result, source_turn)
            except Exception as error:
                raise ToolContinuationCycleCreationError(
                    f"trusted completion recording failed for {safe_context}"
                ) from error
        return cycle
