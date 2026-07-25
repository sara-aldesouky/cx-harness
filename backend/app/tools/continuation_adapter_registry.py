"""In-memory discovery for provider continuation translation adapters."""

from __future__ import annotations

from app.tools.continuation_adapter import ProviderContinuationAdapter


class ProviderContinuationAdapterRegistryError(Exception):
    """Base error for continuation-adapter registry failures."""


class InvalidProviderContinuationAdapterNameError(
    ProviderContinuationAdapterRegistryError, ValueError
):
    """Raised when a provider identity is not a non-empty string."""


class InvalidProviderContinuationAdapterError(
    ProviderContinuationAdapterRegistryError, TypeError
):
    """Raised when a registration does not implement the adapter contract."""


class DuplicateProviderContinuationAdapterRegistrationError(
    ProviderContinuationAdapterRegistryError, ValueError
):
    """Raised when a normalized provider identity is already registered."""


class ProviderContinuationAdapterNotFoundError(
    ProviderContinuationAdapterRegistryError, LookupError
):
    """Raised when no continuation adapter matches a provider identity."""


class ProviderContinuationAdapterRegistry:
    """Map provider identities to explicitly supplied adapter instances.

    Each registry owns its registrations. Discovery returns existing adapter
    instances and never translates outcomes, invokes providers, or executes tools.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderContinuationAdapter] = {}

    def register(
        self,
        provider_name: str,
        adapter: ProviderContinuationAdapter,
    ) -> None:
        """Register one adapter instance under a normalized provider identity."""

        normalized = self._normalize_name(provider_name)
        if not isinstance(adapter, ProviderContinuationAdapter):
            raise InvalidProviderContinuationAdapterError(
                "adapter must implement ProviderContinuationAdapter"
            )
        if normalized in self._adapters:
            raise DuplicateProviderContinuationAdapterRegistrationError(
                f"continuation adapter for provider {normalized!r} is already registered"
            )
        self._adapters[normalized] = adapter

    def get(self, provider_name: str) -> ProviderContinuationAdapter:
        """Return the original adapter registered for a provider identity."""

        normalized = self._normalize_name(provider_name)
        try:
            return self._adapters[normalized]
        except KeyError:
            raise ProviderContinuationAdapterNotFoundError(
                f"continuation adapter for provider {normalized!r} is not registered"
            ) from None

    def has(self, provider_name: str) -> bool:
        """Return whether an adapter is registered for the provider."""

        return self._normalize_name(provider_name) in self._adapters

    def list_providers(self) -> tuple[str, ...]:
        """Return normalized provider identities in deterministic order."""

        return tuple(sorted(self._adapters))

    def items(self) -> tuple[tuple[str, ProviderContinuationAdapter], ...]:
        """Return an immutable, deterministic snapshot of registrations."""

        return tuple((name, self._adapters[name]) for name in sorted(self._adapters))

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise InvalidProviderContinuationAdapterNameError(
                "provider name must be a string"
            )
        normalized = name.strip().lower()
        if not normalized:
            raise InvalidProviderContinuationAdapterNameError(
                "provider name must not be empty or whitespace"
            )
        return normalized
