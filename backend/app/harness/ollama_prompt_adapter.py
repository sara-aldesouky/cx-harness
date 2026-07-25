"""Pure prompt translation for Ollama's local chat request structure."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.harness.prompt import PromptPackage
from app.harness.prompt_adapter import (
    PromptAdapter,
    ProviderRequest,
    ProviderRequestMessage,
)


OllamaRole = Literal["system", "user", "assistant", "tool"]


class OllamaChatMessage(BaseModel):
    """Immutable internal representation of one Ollama chat message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: OllamaRole
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Ollama message content must not be blank")
        return normalized


class OllamaProviderRequest(ProviderRequest):
    """Validated structured request produced for the local Ollama provider."""

    ollama_messages: tuple[OllamaChatMessage, ...]

    @field_validator("ollama_messages")
    @classmethod
    def validate_ollama_messages(
        cls, value: tuple[OllamaChatMessage, ...]
    ) -> tuple[OllamaChatMessage, ...]:
        if not value:
            raise ValueError("Ollama request requires at least one message")
        return value


class OllamaPromptAdapter(PromptAdapter):
    """Translate neutral prompts into deterministic Ollama/Qwen chat messages."""

    def __init__(self, model_name: str = "qwen3:8b") -> None:
        normalized = model_name.strip()
        if not normalized:
            raise ValueError("model_name must not be empty or whitespace")
        self._model_name = normalized

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    def _translate(self, prompt: PromptPackage) -> ProviderRequest:
        neutral_messages = tuple(
            ProviderRequestMessage.model_validate(message.model_dump(mode="python"))
            for message in prompt.messages
        )
        ollama_messages = (
            OllamaChatMessage(
                role="system", content=prompt.system_instructions
            ),
            *(
                OllamaChatMessage(
                    role=message.role.value,
                    content=message.content,
                )
                for message in prompt.messages
            ),
        )
        return OllamaProviderRequest(
            provider_name=self.provider_name,
            model_name=self.model_name,
            system_instructions=prompt.system_instructions,
            messages=neutral_messages,
            ollama_messages=ollama_messages,
        )
