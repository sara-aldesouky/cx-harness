"""Configurable, provider-neutral runtime size and count boundaries."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import Settings
from app.harness.context import ConversationContext, ConversationRole
from app.providers.base import ModelToolLoopTurnResponse
from app.tools.execution_outcome import ToolExecutionOutcome
from app.tools.immutable_json import json_copy
from app.tools.selection import ToolSelectionRequest


class OrchestrationBoundaryViolation(ValueError):
    """Safe deterministic rejection when configured runtime limits are exceeded."""

    def __init__(self, code: str, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class OrchestrationRuntimeLimits(BaseModel):
    """Finite startup-validated limits; unsafe unlimited values are impossible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_user_message_chars: int = Field(gt=0, le=1_000_000)
    max_conversation_history: int = Field(ge=0, le=10_000)
    max_provider_messages: int = Field(gt=0, le=20_000)
    max_provider_turns: int = Field(gt=0, le=100)
    max_tools_exposed: int = Field(gt=0, le=1_000)
    max_tool_calls_per_turn: int = Field(gt=0, le=1_000)
    max_tool_argument_bytes: int = Field(gt=0, le=10_000_000)
    max_tool_result_bytes: int = Field(gt=0, le=50_000_000)
    max_provider_response_bytes: int = Field(gt=0, le=50_000_000)

    @classmethod
    def from_settings(cls, value: Settings) -> OrchestrationRuntimeLimits:
        return cls(
            max_user_message_chars=value.max_user_message_chars,
            max_conversation_history=value.max_conversation_history,
            max_provider_messages=value.max_provider_messages,
            max_provider_turns=value.max_model_turns,
            max_tools_exposed=value.max_tools_exposed,
            max_tool_calls_per_turn=value.max_tool_calls_per_turn,
            max_tool_argument_bytes=value.max_tool_argument_bytes,
            max_tool_result_bytes=value.max_tool_result_bytes,
            max_provider_response_bytes=value.max_provider_response_bytes,
        )


class OrchestrationBoundaryValidator:
    """Validate counts and serialized sizes without logging their payloads."""

    def __init__(self, limits: OrchestrationRuntimeLimits) -> None:
        if not isinstance(limits, OrchestrationRuntimeLimits):
            raise TypeError("limits must be OrchestrationRuntimeLimits")
        self.limits = limits

    def validate_context(self, context: ConversationContext) -> None:
        user_messages = [
            message
            for message in context.messages
            if message.role is ConversationRole.USER
        ]
        if any(
            len(message.content) > self.limits.max_user_message_chars
            for message in user_messages
        ):
            self._reject(
                "user_message_too_large",
                "The user message exceeds the supported size.",
            )
        history_count = max(0, len(context.messages) - 1)
        if history_count > self.limits.max_conversation_history:
            self._reject(
                "conversation_history_too_large",
                "The conversation history exceeds the supported limit.",
            )

    def validate_provider_message_count(self, count: int) -> None:
        if count + 1 > self.limits.max_provider_messages:
            self._reject(
                "provider_message_limit_exceeded",
                "The conversation is too large to continue safely.",
            )

    def validate_provider_response(
        self, response: ModelToolLoopTurnResponse
    ) -> None:
        if self._json_size(response.model_dump(mode="json")) > (
            self.limits.max_provider_response_bytes
        ):
            self._reject(
                "provider_response_too_large",
                "The model response exceeded the supported size.",
            )
        if len(response.tool_calls) > self.limits.max_tool_calls_per_turn:
            self._reject(
                "tool_call_limit_exceeded",
                "The model requested too many tools in one turn.",
            )
        for call in response.tool_calls:
            self.validate_tool_call(call)

    def validate_tool_call(self, call: ToolSelectionRequest) -> None:
        if self._json_size(call.arguments) > self.limits.max_tool_argument_bytes:
            self._reject(
                "tool_arguments_too_large",
                "The requested tool arguments exceed the supported size.",
            )

    def validate_tool_result(self, outcome: ToolExecutionOutcome) -> None:
        if self._json_size(outcome.model_dump(mode="json")) > (
            self.limits.max_tool_result_bytes
        ):
            self._reject(
                "tool_result_too_large",
                "The tool result exceeds the supported size.",
            )

    @staticmethod
    def tool_call_fingerprint(call: ToolSelectionRequest) -> str:
        return json.dumps(
            {
                "name": call.tool_name.strip().lower(),
                "version": call.tool_version,
                "arguments": json_copy(
                    call.model_dump(mode="json")["arguments"]
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _json_size(value: Any) -> int:
        return len(
            json.dumps(
                json_copy(value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )

    @staticmethod
    def _reject(code: str, message: str) -> None:
        raise OrchestrationBoundaryViolation(code, message)
