"""Deterministic network-free adapter for Stage 14 development and tests."""

from __future__ import annotations

from app.model_orchestration.adapter import ModelProviderAdapter
from app.model_orchestration.contracts import (
    ModelFinishReason,
    ModelMessage,
    ModelMessageRole,
    ModelOrchestrationRequest,
    ModelOrchestrationResponse,
    ModelResponseMetadata,
)


class FakeModelProviderAdapter(ModelProviderAdapter):
    def __init__(
        self,
        *,
        provider_name: str = "fake",
        model_identifier: str = "fake-model-v1",
    ) -> None:
        self._provider_name = provider_name.strip().lower()
        self._model_identifier = model_identifier.strip()
        if not self._provider_name or not self._model_identifier:
            raise ValueError("fake provider identity must not be blank")

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_identifier(self) -> str:
        return self._model_identifier

    def invoke(
        self, request: ModelOrchestrationRequest
    ) -> ModelOrchestrationResponse:
        if not isinstance(request, ModelOrchestrationRequest):
            raise TypeError("request must be a ModelOrchestrationRequest")
        customer_message = next(
            message.content
            for message in reversed(request.messages)
            if message.role is ModelMessageRole.USER
        )
        content = f"Fake response: {customer_message}"
        input_tokens = len(request.system_instructions.split()) + sum(
            len(message.content.split()) for message in request.messages
        )
        output_tokens = len(content.split())
        return ModelOrchestrationResponse(
            assistant_message=ModelMessage(
                role=ModelMessageRole.ASSISTANT,
                content=content,
            ),
            metadata=ModelResponseMetadata(
                provider_name=self.provider_name,
                model_identifier=self.model_identifier,
                request_id=f"fake-{request.execution.request_id}",
                latency_ms=0,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                finish_reason=ModelFinishReason.STOP,
            ),
            provider_metadata={"transport": "in_memory"},
        )
