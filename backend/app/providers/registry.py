"""Deterministic in-memory discovery for model provider implementations."""

from __future__ import annotations

from app.providers.base import ModelProvider


class DuplicateProviderRegistrationError(ValueError):
    """Raised when a provider name is already registered."""


class ProviderNotFoundError(LookupError):
    """Raised when no provider matches a requested name."""


class ProviderRegistry:
    """Register and resolve provider instances without knowing their concrete type."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        """Register one provider instance by its normalized provider name."""

        if not isinstance(provider, ModelProvider):
            raise TypeError("provider must implement ModelProvider")
        name = self._normalize_name(provider.provider_name)
        if name in self._providers:
            raise DuplicateProviderRegistrationError(
                f"provider {name!r} is already registered"
            )
        self._providers[name] = provider

    def get(self, name: str) -> ModelProvider:
        """Return a provider through the common interface."""

        normalized = self._normalize_name(name)
        try:
            return self._providers[normalized]
        except KeyError:
            raise ProviderNotFoundError(
                f"provider {normalized!r} is not registered"
            ) from None

    def has(self, name: str) -> bool:
        """Return whether the normalized provider name is registered."""

        return self._normalize_name(name) in self._providers

    def list(self) -> tuple[ModelProvider, ...]:
        """Return providers deterministically ordered by registered name."""

        return tuple(self._providers[name] for name in sorted(self._providers))

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("provider name must be a string")
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("provider name must not be empty or whitespace")
        return normalized
