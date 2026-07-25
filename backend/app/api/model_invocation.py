"""Transport-neutral mapping between API contracts and application service."""

from __future__ import annotations

from typing import Protocol

from app.authentication import TrustedCustomerIdentity
from app.harness.context import ConversationMessage
from app.schemas.model_invocation import (
    ModelInvocationRequest,
    ModelInvocationResponse,
)
from app.services.model_pipeline_service import (
    ModelPipelineServiceResult,
)
from app.data_protection import privacy_service


class ModelInvocationService(Protocol):
    """Application-service behavior required by the future API layer."""

    def invoke(self, **kwargs: object) -> ModelPipelineServiceResult: ...


class ModelInvocationMapper:
    """Map one public request through the application service into a response."""

    def __init__(
        self,
        *,
        service: ModelInvocationService,
        default_system_instructions: str,
    ) -> None:
        if not callable(getattr(service, "invoke", None)):
            raise TypeError("service must provide a callable invoke() method")
        normalized_default = default_system_instructions.strip()
        if not normalized_default:
            raise ValueError("default_system_instructions must not be blank")
        self._service = service
        self._default_system_instructions = normalized_default

    def invoke(
        self,
        request: ModelInvocationRequest,
        identity: TrustedCustomerIdentity,
    ) -> ModelInvocationResponse:
        """Invoke exactly once while preserving application-service exceptions."""

        if not isinstance(request, ModelInvocationRequest):
            raise TypeError("request must be a ModelInvocationRequest")
        if not isinstance(identity, TrustedCustomerIdentity):
            raise TypeError("identity must be a TrustedCustomerIdentity")
        validated_request = ModelInvocationRequest.model_validate(
            request.model_dump(mode="python")
        )
        history = tuple(
            ConversationMessage(
                role=message.role,
                content=message.content,
            )
            for message in validated_request.conversation_history
        )
        result = self._service.invoke(
            conversation_id=validated_request.conversation_id,
            current_user_message=validated_request.current_user_message,
            conversation_history=history,
            system_instructions=(
                validated_request.system_instructions
                or self._default_system_instructions
            ),
            trusted_identity=identity,
        )
        return self.to_response(result)

    @staticmethod
    def to_response(
        result: ModelPipelineServiceResult,
    ) -> ModelInvocationResponse:
        """Map an immutable application result into the public response contract."""

        if not isinstance(result, ModelPipelineServiceResult):
            raise TypeError("result must be a ModelPipelineServiceResult")
        validated_result = ModelPipelineServiceResult.model_validate(
            result.model_dump(mode="python")
        )
        return ModelInvocationResponse(
            content=privacy_service.protect_text(validated_result.content),
            provider_name=validated_result.provider_name,
            model_name=validated_result.model_name,
        )
