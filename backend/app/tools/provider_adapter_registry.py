"""In-memory discovery for provider tool-call translation adapters."""

from __future__ import annotations

from app.tools.provider_adapter import ProviderToolCallAdapter


class ProviderToolCallAdapterRegistryError(Exception):
    """Base error for adapter-registry configuration and lookup failures."""


class InvalidProviderToolCallAdapterNameError(
    ProviderToolCallAdapterRegistryError, ValueError
):
    """Raised when a provider identity is not a non-empty string."""


class InvalidProviderToolCallAdapterError(
    ProviderToolCallAdapterRegistryError, TypeError
):
    """Raised when a registration does not implement the adapter contract."""


class DuplicateProviderToolCallAdapterRegistrationError(
    ProviderToolCallAdapterRegistryError, ValueError
):
    """Raised when a normalized provider identity is already registered."""


class ProviderToolCallAdapterNotFoundError(
    ProviderToolCallAdapterRegistryError, LookupError
):
    """Raised when no adapter matches a normalized provider identity."""


class ProviderToolCallAdapterRegistry:
    """Map provider identities to explicitly supplied adapter instances.

    The registry has no global state and never calls an adapter. It only stores
    already-created translation adapters so future orchestration can receive the
    registry through dependency injection.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderToolCallAdapter] = {}

    def register(
        self,
        provider_name: str,
        adapter: ProviderToolCallAdapter,
    ) -> None:
        """Register one adapter instance under a normalized provider name."""

        normalized = self._normalize_name(provider_name)
        if not isinstance(adapter, ProviderToolCallAdapter):
            raise InvalidProviderToolCallAdapterError(
                "adapter must implement ProviderToolCallAdapter"
            )
        if normalized in self._adapters:
            raise DuplicateProviderToolCallAdapterRegistrationError(
                f"tool-call adapter for provider {normalized!r} is already registered"
            )
        self._adapters[normalized] = adapter

    def get(self, provider_name: str) -> ProviderToolCallAdapter:
        """Return the adapter registered for a normalized provider identity."""

        normalized = self._normalize_name(provider_name)
        try:
            return self._adapters[normalized]
        except KeyError:
            raise ProviderToolCallAdapterNotFoundError(
                f"tool-call adapter for provider {normalized!r} is not registered"
            ) from None

    def has(self, provider_name: str) -> bool:
        """Return whether an adapter is registered for the provider."""

        return self._normalize_name(provider_name) in self._adapters

    def list_providers(self) -> tuple[str, ...]:
        """Return normalized provider names in deterministic order."""

        return tuple(sorted(self._adapters))

    def items(self) -> tuple[tuple[str, ProviderToolCallAdapter], ...]:
        """Return an immutable deterministic snapshot of registrations."""

        return tuple((name, self._adapters[name]) for name in sorted(self._adapters))

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise InvalidProviderToolCallAdapterNameError(
                "provider name must be a string"
            )
        normalized = name.strip().lower()
        if not normalized:
            raise InvalidProviderToolCallAdapterNameError(
                "provider name must not be empty or whitespace"
            )
        return normalized
