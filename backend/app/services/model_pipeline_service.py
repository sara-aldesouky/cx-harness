"""Application boundary for one trusted model-pipeline invocation."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from typing import Callable, Optional, Protocol
from uuid import UUID
from app.authentication import TrustedCustomerIdentity

from pydantic import BaseModel, ConfigDict, field_validator

from app.config.settings import settings
from app.harness.context import ConversationMessage, ConversationRole
from app.harness.context_builder import ContextBuilder, MessageInput
from app.harness.model_pipeline import ModelPipelineCoordinator
from app.harness.runtime import build_model_pipeline
from app.providers.base import ModelResponse
from app.data_protection import DataProtectionService, privacy_service
from app.security_audit import (
    AuditCategory,
    AuditResult,
    AuditSeverity,
    SecurityEventType,
    security_audit_recorder,
)


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
        data_protection: DataProtectionService = privacy_service,
    ) -> None:
        self._pipeline = pipeline
        self._pipeline_factory = pipeline_factory
        self._provider_name = provider_name
        self._model_name = model_name
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
    ) -> ModelPipelineServiceResult:
        """Build trusted context, invoke once, and map the standardized response."""

        if not isinstance(conversation_id, UUID):
            raise ModelPipelineServiceInputError(
                "conversation_id must be a valid UUID"
            )
        if not isinstance(trusted_identity, TrustedCustomerIdentity):
            raise ModelPipelineServiceInputError(
                "trusted_identity must be authenticated"
            )
        if isinstance(conversation_history, (str, bytes)):
            raise TypeError(
                "conversation_history must be an ordered message collection"
            )

        protected_current = self._data_protection.protect_text(current_user_message)
        current_message = ConversationMessage(
            role=ConversationRole.USER,
            content=protected_current,
        )
        history_inputs = tuple(conversation_history)
        protected_history = tuple(
            self._data_protection.protect_message_input(message)
            for message in history_inputs
        )
        if (
            protected_current != current_user_message
            or self._data_protection.protect_text(system_instructions)
            != system_instructions.strip()
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
            system_instructions=self._data_protection.protect_text(system_instructions),
            messages=chain(protected_history, (current_message,)),
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
        safe_content = self._data_protection.protect_text(validated_response.content)
        if safe_content != validated_response.content:
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
            provider_name=validated_response.provider_name,
            model_name=validated_response.model_name,
        )
