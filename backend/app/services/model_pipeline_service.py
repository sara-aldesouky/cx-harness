"""Application boundary for one trusted model-pipeline invocation."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from typing import Callable, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.config.settings import settings
from app.harness.context import ConversationMessage, ConversationRole
from app.harness.context_builder import ContextBuilder, MessageInput
from app.harness.model_pipeline import ModelPipelineCoordinator
from app.harness.runtime import build_model_pipeline
from app.providers.base import ModelResponse


class ModelPipelineInvoker(Protocol):
    """Narrow coordinator behavior required by the application service."""

    def run(
        self,
        *,
        system_instructions: str,
        messages: Iterable[MessageInput],
        provider_name: str,
        model_name: str,
        conversation_id: Optional[UUID] = None,
    ) -> ModelResponse: ...


class ModelPipelineServiceResult(BaseModel):
    """Immutable application-safe result without transport or persistence details."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str
    provider_name: str
    model_name: str

    @field_validator("content", "provider_name", "model_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty or whitespace")
        return normalized


class ModelPipelineServiceInputError(ValueError):
    """Raised when trusted invocation identity is missing or malformed."""


class ModelPipelineServiceConfigurationError(RuntimeError):
    """Raised when an injected pipeline does not satisfy the service contract."""


class ModelPipelineService:
    """Validate application inputs and invoke exactly one configured pipeline.

    Construction is side-effect free. Runtime composition is lazy unless a
    coordinator is injected directly for an application entry point or test.
    """

    def __init__(
        self,
        *,
        pipeline: Optional[ModelPipelineInvoker] = None,
        pipeline_factory: Callable[[], ModelPipelineCoordinator] = (
            build_model_pipeline
        ),
        provider_name: str = "ollama",
        model_name: str = settings.ollama_model_name,
    ) -> None:
        self._pipeline = pipeline
        self._pipeline_factory = pipeline_factory
        self._provider_name = provider_name
        self._model_name = model_name

    def invoke(
        self,
        *,
        conversation_id: UUID,
        current_user_message: str,
        conversation_history: Iterable[MessageInput] = (),
        system_instructions: str,
    ) -> ModelPipelineServiceResult:
        """Build trusted context, invoke once, and map the standardized response."""

        if not isinstance(conversation_id, UUID):
            raise ModelPipelineServiceInputError(
                "conversation_id must be a valid UUID"
            )
        if isinstance(conversation_history, (str, bytes)):
            raise TypeError(
                "conversation_history must be an ordered message collection"
            )

        current_message = ConversationMessage(
            role=ConversationRole.USER,
            content=current_user_message,
        )
        context = ContextBuilder.build(
            system_instructions=system_instructions,
            messages=chain(conversation_history, (current_message,)),
            provider_name=self._provider_name,
            model_name=self._model_name,
        )

        pipeline = self._pipeline
        if pipeline is None:
            pipeline = self._pipeline_factory()
        if not callable(getattr(pipeline, "run", None)):
            raise ModelPipelineServiceConfigurationError(
                "configured pipeline must provide a callable run() method"
            )

        response = pipeline.run(
            system_instructions=context.system_instructions,
            messages=context.messages,
            provider_name=context.provider_name or self._provider_name,
            model_name=context.model_name or self._model_name,
            conversation_id=conversation_id,
        )
        if not isinstance(response, ModelResponse):
            raise ModelPipelineServiceConfigurationError(
                "configured pipeline must return a ModelResponse"
            )
        validated_response = ModelResponse.model_validate(
            response.model_dump(mode="python")
        )
        return ModelPipelineServiceResult(
            content=validated_response.content,
            provider_name=validated_response.provider_name,
            model_name=validated_response.model_name,
        )
