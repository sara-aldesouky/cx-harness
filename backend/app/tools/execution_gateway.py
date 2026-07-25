"""Single-request application boundary over the existing ToolExecutor."""

from __future__ import annotations

from pydantic import ValidationError

from app.tools.execution_request import ToolExecutionRequest
from app.tools.executor import ToolExecutor
from app.tools.immutable_json import json_copy
from app.tools.registry import ToolRegistry
from app.tools.result import ToolResult


class SingleToolExecutionGatewayError(Exception):
    """Base error for failures added specifically by the gateway boundary."""


class InvalidToolExecutionGatewayRequestError(
    SingleToolExecutionGatewayError, TypeError
):
    """Raised when execution is attempted without ToolExecutionRequest."""


class DisabledToolExecutionError(SingleToolExecutionGatewayError):
    """Raised when a tool was disabled after selection and before execution."""


class ToolInputRehydrationError(SingleToolExecutionGatewayError):
    """Raised when validated JSON cannot be rebuilt as the registered input model."""


class SingleToolExecutionGateway:
    """Adapt exactly one trusted request to the existing execution engine.

    Exact lookup and enablement are checked immediately before delegation to
    protect against runtime registry changes. Tool construction, invocation,
    result verification, auditing, and persistence remain exclusively owned by
    ``ToolExecutor``.
    """

    def __init__(self, registry: ToolRegistry, executor: ToolExecutor) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        if not isinstance(executor, ToolExecutor):
            raise TypeError("executor must be a ToolExecutor")
        self._registry = registry
        self._executor = executor

    def execute(self, request: ToolExecutionRequest) -> ToolResult:
        """Execute one exact request once and return the executor result unchanged."""

        if not isinstance(request, ToolExecutionRequest):
            raise InvalidToolExecutionGatewayRequestError(
                "request must be a ToolExecutionRequest"
            )

        tool_class = self._registry.get(request.tool_name, request.tool_version)
        if not tool_class.metadata.is_enabled:
            raise DisabledToolExecutionError(
                f"tool {request.tool_name!r} version "
                f"{request.tool_version!r} is disabled"
            )

        try:
            input_model = tool_class.input_schema.model_validate(
                json_copy(request.arguments)
            )
        except ValidationError as error:
            raise ToolInputRehydrationError(
                f"validated input for tool {request.tool_name!r} "
                "could not be rehydrated"
            ) from error

        return self._executor.execute(
            request.tool_name,
            request.tool_version,
            request.context,
            input_model,
        )
