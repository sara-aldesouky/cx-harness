"""Provider prompt-adapter contract and deterministic offline implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.harness.prompt import PromptMessage, PromptPackage


class ProviderRequestMessage(PromptMessage):
    """Immutable message at the provider-translation boundary."""


class ProviderRequest(BaseModel):
    """Immutable standardized result of provider prompt translation.

    This is an internal adapter-boundary representation, not an HTTP or SDK
    payload. Future concrete adapters may use it before their transport layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str
    model_name: str
    system_instructions: str
    messages: tuple[ProviderRequestMessage, ...]

    @field_validator("provider_name", "model_name", "system_instructions")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """Normalize required text and reject blank translated fields."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty or whitespace")
        return normalized

    @field_validator("messages")
    @classmethod
    def validate_messages(
        cls, value: tuple[ProviderRequestMessage, ...]
    ) -> tuple[ProviderRequestMessage, ...]:
        """Require an ordered, non-empty translated message sequence."""

        if not value:
            raise ValueError("provider request requires at least one message")
        return value


class PromptAdapterContractError(TypeError):
    """Raised when an adapter violates its standardized output contract."""


class PromptAdapter(ABC):
    """Template-method boundary for provider-owned prompt translation.

    The public operation enforces shared validation. Concrete adapters own only
    translation and must not leak their formatting into the rest of the harness.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identity represented by this adapter."""

        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identity represented by this adapter."""

        raise NotImplementedError

    def adapt(self, prompt: PromptPackage) -> ProviderRequest:
        """Validate, translate, and revalidate one neutral prompt package."""

        if not isinstance(prompt, PromptPackage):
            raise TypeError("prompt must be a PromptPackage")
        validated_prompt = PromptPackage.model_validate(
            prompt.model_dump(mode="python")
        )
        provider_name = self._validated_identity(
            self.provider_name, "provider_name"
        )
        model_name = self._validated_identity(self.model_name, "model_name")

        if (
            validated_prompt.provider_name is not None
            and validated_prompt.provider_name != provider_name
        ):
            raise ValueError("prompt provider selection does not match adapter")
        if (
            validated_prompt.model_name is not None
            and validated_prompt.model_name != model_name
        ):
            raise ValueError("prompt model selection does not match adapter")

        translated = self._translate(validated_prompt)
        if not isinstance(translated, ProviderRequest):
            raise PromptAdapterContractError(
                "adapter translation must return a ProviderRequest"
            )
        try:
            validated_request = translated.__class__.model_validate(
                translated.model_dump(mode="python")
            )
        except ValidationError as exc:
            raise PromptAdapterContractError(
                "adapter returned an invalid ProviderRequest"
            ) from exc

        if validated_request.provider_name != provider_name:
            raise PromptAdapterContractError(
                "translated provider_name does not match adapter"
            )
        if validated_request.model_name != model_name:
            raise PromptAdapterContractError(
                "translated model_name does not match adapter"
            )
        return validated_request

    @abstractmethod
    def _translate(self, prompt: PromptPackage) -> ProviderRequest:
        """Translate validated neutral data without performing model invocation."""

        raise NotImplementedError

    @staticmethod
    def _validated_identity(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PromptAdapterContractError(
                f"adapter {field_name} must be a non-empty string"
            )
        return value.strip()


class MockPromptAdapter(PromptAdapter):
    """Deterministic offline translation used for development and tests."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-deterministic-v1"

    def _translate(self, prompt: PromptPackage) -> ProviderRequest:
        messages = tuple(
            ProviderRequestMessage.model_validate(
                message.model_dump(mode="python")
            )
            for message in prompt.messages
        )
        return ProviderRequest(
            provider_name=self.provider_name,
            model_name=self.model_name,
            system_instructions=prompt.system_instructions,
            messages=messages,
        )
