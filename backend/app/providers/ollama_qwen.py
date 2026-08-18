"""Local Qwen model provider implemented through Ollama's chat API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

import httpx

from app.providers.base import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelToolLoopTurnResponse,
    ProviderCapabilities,
)
from app.tools.immutable_json import json_copy
from app.tools.continuation_adapter import (
    ProviderContinuationAdapter,
    ProviderContinuationPayload,
)
from app.tools.execution_outcome import ToolExecutionOutcome
from app.tools.result import ToolStatus
from app.tools.selection import ToolSelectionRequest

if TYPE_CHECKING:
    from app.harness.prompt_adapter import ProviderRequest
    from app.services.model_tool_loop_service import ModelToolLoopTurnRequest


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OllamaInvocationMetadata:
    """Safe operational measurements for one local provider request."""

    thinking_enabled: bool
    context_size: int
    output_token_cap: int
    timeout_seconds: float
    keep_alive: str
    cache_state: str
    prompt_tokens: Optional[int]
    output_tokens: Optional[int]
    total_latency_ms: float
    outcome: str


class OllamaProviderError(RuntimeError):
    """Base error for local Ollama provider failures."""


class OllamaUnavailableError(OllamaProviderError):
    """Raised when the configured local Ollama service cannot be reached."""


class OllamaRequestTimeoutError(OllamaProviderError, TimeoutError):
    """Raised when a local Ollama request exceeds its configured timeout."""


class InvalidOllamaResponseError(OllamaProviderError):
    """Raised when Ollama returns invalid JSON or an unsupported structure."""


class EmptyModelResponseError(OllamaProviderError):
    """Raised when Ollama returns no usable assistant content."""


class OllamaProviderContinuationAdapter(ProviderContinuationAdapter):
    """Translate one normalized outcome into Ollama-safe result information."""

    @property
    def provider_name(self) -> str:
        return "ollama"

    def translate(
        self, outcome: ToolExecutionOutcome
    ) -> ProviderContinuationPayload:
        if not isinstance(outcome, ToolExecutionOutcome):
            raise TypeError("outcome must be a ToolExecutionOutcome")
        if outcome.status is ToolStatus.SUCCESS:
            result: dict[str, Any] = {
                "status": "success",
                "output": json_copy(outcome.output or {}),
            }
        else:
            result = {
                "status": "failure",
                "error": outcome.error.model_dump(mode="json") if outcome.error else {},
            }
        return ProviderContinuationPayload(
            provider_name=self.provider_name,
            call_id=outcome.call_id,
            payload={
                "type": "tool_result",
                "tool_name": outcome.tool_name,
                **result,
            },
        )


class OllamaQwenProvider(ModelProvider):
    """Synchronous provider for one configured Qwen model on local Ollama."""

    _capabilities = ProviderCapabilities(tool_calling=True)

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model_name: str = "qwen3:8b",
        connect_timeout_seconds: float = 2.0,
        read_timeout_seconds: float = 60.0,
        client: Optional[httpx.Client] = None,
        tool_definitions: Sequence[Mapping[str, Any]] = (),
        max_response_bytes: int = 1_048_576,
        context_size: int = 8_192,
        max_output_tokens: int = 256,
        keep_alive: str = "15m",
        tool_thinking_enabled: bool = False,
    ) -> None:
        self._base_url = self._validate_local_base_url(base_url)
        normalized_model = model_name.strip()
        if not normalized_model:
            raise ValueError("model_name must not be empty or whitespace")
        if connect_timeout_seconds <= 0 or read_timeout_seconds <= 0:
            raise ValueError("Ollama timeouts must be greater than zero")
        if (
            not isinstance(max_response_bytes, int)
            or isinstance(max_response_bytes, bool)
            or max_response_bytes <= 0
            or max_response_bytes > 50_000_000
        ):
            raise ValueError("max_response_bytes must be between 1 and 50000000")
        self._model_name = normalized_model
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._client = client
        self._max_response_bytes = max_response_bytes
        if isinstance(context_size, bool) or not 4_096 <= context_size <= 131_072:
            raise ValueError("context_size must be between 4096 and 131072")
        if (
            isinstance(max_output_tokens, bool)
            or not 1 <= max_output_tokens <= 8_192
        ):
            raise ValueError("max_output_tokens must be between 1 and 8192")
        normalized_keep_alive = keep_alive.strip().lower()
        if not normalized_keep_alive:
            raise ValueError("keep_alive must not be blank")
        if not isinstance(tool_thinking_enabled, bool):
            raise TypeError("tool_thinking_enabled must be a boolean")
        self._context_size = context_size
        self._max_output_tokens = max_output_tokens
        self._keep_alive = normalized_keep_alive
        self._tool_thinking_enabled = tool_thinking_enabled
        self._read_timeout_seconds = float(read_timeout_seconds)
        self._last_invocation_metadata: Optional[OllamaInvocationMetadata] = None
        self._tools = self._translate_tool_definitions(tool_definitions)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def last_invocation_metadata(self) -> Optional[OllamaInvocationMetadata]:
        """Return safe measurements without request content or identity data."""

        return self._last_invocation_metadata

    def prewarm(self) -> OllamaInvocationMetadata:
        """Load and validate the production prompt/tool payload without execution."""

        from app.harness.production_prompt import PRODUCTION_SYSTEM_PROMPT

        body = self._request_chat(
            [
                {"role": "system", "content": PRODUCTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Internal readiness check only. Return a concise response "
                        "or one valid tool-call structure; do not use customer data."
                    ),
                },
            ],
            tools=self._tools,
        )
        message = self._extract_assistant_message(body)
        native_calls = message.get("tool_calls") or []
        content = message.get("content")
        if native_calls:
            if not isinstance(native_calls, list):
                raise InvalidOllamaResponseError("Ollama tool_calls must be an array")
            self._parse_tool_calls(native_calls, 1)
        elif not isinstance(content, str) or not content.strip():
            raise EmptyModelResponseError(
                "local Ollama prewarm returned no usable response"
            )
        if self._last_invocation_metadata is None:
            raise InvalidOllamaResponseError("Ollama prewarm metadata is unavailable")
        return self._last_invocation_metadata

    def close(self) -> None:
        """Close an injected HTTP client; per-request clients close automatically."""

        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Preserve the Stage 7.1 text request path as one user chat message."""

        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        return self._post_chat(
            [{"role": "user", "content": request.prompt}]
        )

    def generate_provider_request(
        self, request: ProviderRequest
    ) -> ModelResponse:
        """Invoke Ollama with a request created by OllamaPromptAdapter."""

        from app.harness.ollama_prompt_adapter import OllamaProviderRequest

        if not isinstance(request, OllamaProviderRequest):
            raise TypeError("request must be an OllamaProviderRequest")
        validated = OllamaProviderRequest.model_validate(
            request.model_dump(mode="python")
        )
        if validated.provider_name != self.provider_name:
            raise ValueError("request provider_name does not match provider")
        if validated.model_name != self.model_name:
            raise ValueError("request model_name does not match provider")
        messages = [
            message.model_dump(mode="json")
            for message in validated.ollama_messages
        ]
        return self._post_chat(messages)

    def run_tool_loop_turn(
        self, request: ModelToolLoopTurnRequest
    ) -> ModelToolLoopTurnResponse:
        """Translate one normalized loop turn through Ollama's local chat API."""

        from app.services.model_tool_loop_service import ModelToolLoopTurnRequest

        if not isinstance(request, ModelToolLoopTurnRequest):
            raise TypeError("request must be a ModelToolLoopTurnRequest")
        if request.provider_name != self.provider_name:
            raise ValueError("request provider_name does not match provider")
        if request.model_name != self.model_name:
            raise ValueError("request model_name does not match provider")

        messages = self._to_ollama_loop_messages(request)
        body = self._request_chat(messages, tools=self._tools)
        message = self._extract_assistant_message(body)
        native_calls = message.get("tool_calls", [])
        if native_calls is None:
            native_calls = []
        if not isinstance(native_calls, list):
            raise InvalidOllamaResponseError("Ollama tool_calls must be an array")
        if native_calls:
            selections = self._parse_tool_calls(native_calls, request.turn_number)
            content = message.get("content")
            assistant_content = content.strip() if isinstance(content, str) and content.strip() else None
            return ModelToolLoopTurnResponse(
                tool_calls=selections,
                assistant_content=assistant_content,
            )

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise EmptyModelResponseError("local Ollama returned empty assistant content")
        return ModelToolLoopTurnResponse(
            final_response=ModelResponse(
                content=content.strip(),
                provider_name=self.provider_name,
                model_name=self.model_name,
            )
        )

    def _post_chat(self, messages: list[dict[str, str]]) -> ModelResponse:
        body = self._request_chat(messages)
        message = self._extract_assistant_message(body)
        content = message.get("content")
        if not isinstance(content, str):
            raise InvalidOllamaResponseError(
                "local Ollama response content must be text"
            )
        normalized_content = content.strip()
        if not normalized_content:
            raise EmptyModelResponseError(
                "local Ollama returned empty assistant content"
            )
        return ModelResponse(
            content=normalized_content,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

    def _request_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {
                "num_ctx": self._context_size,
                "num_predict": self._max_output_tokens,
            },
        }
        if tools:
            payload["tools"] = list(tools)
            payload["think"] = self._tool_thinking_enabled
        started = monotonic()
        try:
            if self._client is not None:
                response = self._client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                    timeout=self._timeout,
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        f"{self._base_url}/api/chat", json=payload
                    )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            self._record_invocation_metadata(
                body=None,
                started=started,
                tools_enabled=bool(tools),
                outcome="timeout",
            )
            raise OllamaRequestTimeoutError("local Ollama request timed out") from exc
        except httpx.RequestError as exc:
            self._record_invocation_metadata(
                body=None,
                started=started,
                tools_enabled=bool(tools),
                outcome="unavailable",
            )
            raise OllamaUnavailableError(
                "local Ollama service is unavailable"
            ) from exc
        except httpx.HTTPStatusError as exc:
            self._record_invocation_metadata(
                body=None,
                started=started,
                tools_enabled=bool(tools),
                outcome="http_error",
            )
            raise OllamaUnavailableError(
                f"local Ollama returned HTTP {exc.response.status_code}"
            ) from exc

        if len(response.content) > self._max_response_bytes:
            raise InvalidOllamaResponseError(
                "local Ollama response exceeds the configured size limit"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise InvalidOllamaResponseError(
                "local Ollama returned invalid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise InvalidOllamaResponseError(
                "local Ollama response must be a JSON object"
            )
        self._record_invocation_metadata(
            body=body,
            started=started,
            tools_enabled=bool(tools),
            outcome="completed",
        )
        return body

    def _record_invocation_metadata(
        self,
        *,
        body: Optional[Mapping[str, Any]],
        started: float,
        tools_enabled: bool,
        outcome: str,
    ) -> None:
        load_duration = body.get("load_duration") if body is not None else None
        if isinstance(load_duration, (int, float)):
            cache_state = "cold" if load_duration >= 1_000_000_000 else "warm"
        else:
            cache_state = "unknown"
        prompt_tokens = body.get("prompt_eval_count") if body is not None else None
        output_tokens = body.get("eval_count") if body is not None else None
        metadata = OllamaInvocationMetadata(
            thinking_enabled=(
                self._tool_thinking_enabled if tools_enabled else True
            ),
            context_size=self._context_size,
            output_token_cap=self._max_output_tokens,
            timeout_seconds=self._read_timeout_seconds,
            keep_alive=self._keep_alive,
            cache_state=cache_state,
            prompt_tokens=(prompt_tokens if isinstance(prompt_tokens, int) else None),
            output_tokens=(output_tokens if isinstance(output_tokens, int) else None),
            total_latency_ms=max(0.0, (monotonic() - started) * 1000),
            outcome=outcome,
        )
        self._last_invocation_metadata = metadata
        logger.info(
            "ollama_invocation thinking_enabled=%s context_size=%s "
            "output_token_cap=%s timeout_seconds=%s keep_alive=%s "
            "cache_state=%s prompt_tokens=%s output_tokens=%s "
            "total_latency_ms=%.3f outcome=%s",
            metadata.thinking_enabled,
            metadata.context_size,
            metadata.output_token_cap,
            metadata.timeout_seconds,
            metadata.keep_alive,
            metadata.cache_state,
            metadata.prompt_tokens,
            metadata.output_tokens,
            metadata.total_latency_ms,
            metadata.outcome,
        )

    @staticmethod
    def _extract_assistant_message(body: Mapping[str, Any]) -> dict[str, Any]:
        message = body.get("message")
        if not isinstance(message, dict):
            raise InvalidOllamaResponseError(
                "local Ollama response is missing message data"
            )
        if message.get("role") != "assistant":
            raise InvalidOllamaResponseError(
                "local Ollama response has an unsupported message role"
            )
        return message

    def _to_ollama_loop_messages(
        self, request: ModelToolLoopTurnRequest
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.context.system_instructions}
        ]
        calls_by_id = {call.call_id: call for call in request.tool_call_history}
        for message in request.context.messages:
            metadata = dict(message.metadata)
            if (
                message.role.value == "assistant"
                and metadata.get("message_type") == "tool_calls"
            ):
                call_ids = tuple(
                    part for part in metadata.get("call_ids", "").split(",") if part
                )
                native_calls = [
                    self._selection_to_native(calls_by_id[call_id], index)
                    for index, call_id in enumerate(call_ids)
                    if call_id in calls_by_id
                ]
                if len(native_calls) != len(call_ids):
                    raise InvalidOllamaResponseError(
                        "normalized tool-call history is incomplete"
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": native_calls,
                    }
                )
            elif message.role.value == "tool":
                tool_name = metadata.get("tool_name")
                if not tool_name:
                    raise InvalidOllamaResponseError(
                        "normalized tool-result message is missing tool_name"
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": message.content,
                    }
                )
            else:
                messages.append(
                    {"role": message.role.value, "content": message.content}
                )
        return messages

    @staticmethod
    def _selection_to_native(
        selection: ToolSelectionRequest, index: int
    ) -> dict[str, Any]:
        return {
            "id": selection.call_id,
            "type": "function",
            "function": {
                "index": index,
                "name": selection.tool_name,
                "arguments": json_copy(selection.arguments),
            },
        }

    @staticmethod
    def _parse_tool_calls(
        native_calls: list[Any], turn_number: int
    ) -> tuple[ToolSelectionRequest, ...]:
        selections: list[ToolSelectionRequest] = []
        for index, native_call in enumerate(native_calls):
            if not isinstance(native_call, dict):
                raise InvalidOllamaResponseError("Ollama tool call must be an object")
            function = native_call.get("function")
            if not isinstance(function, dict):
                raise InvalidOllamaResponseError("Ollama tool call is missing function")
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str) or not name.strip():
                raise InvalidOllamaResponseError("Ollama tool call name is invalid")
            if not isinstance(arguments, dict):
                raise InvalidOllamaResponseError("Ollama tool arguments must be an object")
            native_id = native_call.get("id")
            if not isinstance(native_id, str) or not native_id.strip():
                raise InvalidOllamaResponseError(
                    "Ollama tool call ID is missing or invalid"
                )
            call_id = native_id.strip()
            selections.append(
                ToolSelectionRequest(
                    call_id=call_id,
                    tool_name=name,
                    arguments=arguments,
                )
            )
        return tuple(selections)

    @staticmethod
    def _translate_tool_definitions(
        definitions: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        translated: list[dict[str, Any]] = []
        for definition in definitions:
            name = definition.get("name")
            description = definition.get("description")
            parameters = definition.get("input_schema")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tool definition requires a name")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("tool definition requires a description")
            if not isinstance(parameters, Mapping):
                raise ValueError("tool definition requires an input schema")
            translated.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": json_copy(parameters),
                    },
                }
            )
        return tuple(translated)

    @staticmethod
    def _validate_local_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Ollama base URL must use HTTP or HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("Ollama base URL must not contain credentials")
        if (parsed.hostname or "").lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Ollama base URL must target the local machine")
        return normalized
