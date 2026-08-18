"""Deterministic injectable registry for Stage 14 provider adapters."""

from __future__ import annotations

from app.model_orchestration.adapter import ModelProviderAdapter


class ModelAdapterRegistryError(RuntimeError):
    pass


class DuplicateModelAdapterError(ModelAdapterRegistryError):
    pass


class ModelAdapterNotFoundError(ModelAdapterRegistryError, LookupError):
    pass


class ModelProviderAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ModelProviderAdapter] = {}

    def register(self, adapter: ModelProviderAdapter) -> None:
        if not isinstance(adapter, ModelProviderAdapter):
            raise TypeError("adapter must implement ModelProviderAdapter")
        name = self._normalize(adapter.provider_name)
        if name in self._adapters:
            raise DuplicateModelAdapterError(
                f"adapter for provider {name!r} is already registered"
            )
        self._adapters[name] = adapter

    def get(self, provider_name: str) -> ModelProviderAdapter:
        name = self._normalize(provider_name)
        try:
            return self._adapters[name]
        except KeyError:
            raise ModelAdapterNotFoundError(
                f"adapter for provider {name!r} is not registered"
            ) from None

    def has(self, provider_name: str) -> bool:
        return self._normalize(provider_name) in self._adapters

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    @staticmethod
    def _normalize(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("provider_name must be a string")
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name must not be blank")
        return normalized
