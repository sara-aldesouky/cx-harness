"""Deterministic in-memory registry for provider prompt adapters."""

from __future__ import annotations

from app.harness.prompt_adapter import PromptAdapter


class DuplicatePromptAdapterRegistrationError(ValueError):
    """Raised when a provider already has a registered prompt adapter."""


class PromptAdapterNotFoundError(LookupError):
    """Raised when no prompt adapter matches a provider name."""


class PromptAdapterRegistry:
    """Register and resolve adapter instances by normalized provider identity."""

    def __init__(self) -> None:
        self._adapters: dict[str, PromptAdapter] = {}

    def register(self, adapter: PromptAdapter) -> None:
        if not isinstance(adapter, PromptAdapter):
            raise TypeError("adapter must implement PromptAdapter")
        name = self._normalize_name(adapter.provider_name)
        if name in self._adapters:
            raise DuplicatePromptAdapterRegistrationError(
                f"prompt adapter {name!r} is already registered"
            )
        self._adapters[name] = adapter

    def get(self, provider_name: str) -> PromptAdapter:
        normalized = self._normalize_name(provider_name)
        try:
            return self._adapters[normalized]
        except KeyError:
            raise PromptAdapterNotFoundError(
                f"prompt adapter {normalized!r} is not registered"
            ) from None

    def has(self, provider_name: str) -> bool:
        return self._normalize_name(provider_name) in self._adapters

    def list(self) -> tuple[PromptAdapter, ...]:
        return tuple(self._adapters[name] for name in sorted(self._adapters))

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("provider name must be a string")
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("provider name must not be empty or whitespace")
        return normalized
