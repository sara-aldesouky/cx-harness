"""Provider-neutral orchestration for tool-call translation and validation."""

from __future__ import annotations

from app.tools.provider_adapter import ProviderToolCallAdapterError
from app.tools.provider_adapter_registry import (
    ProviderToolCallAdapterRegistry,
    ProviderToolCallAdapterRegistryError,
)
from app.tools.registry import AmbiguousToolLookupError, ToolNotFoundError
from app.tools.selection import (
    DisabledToolSelectionError,
    InvalidToolArgumentsError,
    InvalidToolSelectionRequestError,
    ToolSelectionResolver,
    ValidatedToolSelection,
)


ValidatedToolSelections = tuple[ValidatedToolSelection, ...]


class ToolSelectionServiceError(Exception):
    """Base error for translation-and-validation orchestration failures."""


class ToolSelectionAdapterLookupError(ToolSelectionServiceError):
    """Raised when the service cannot resolve a provider translation adapter."""


class ToolSelectionTranslationError(ToolSelectionServiceError):
    """Raised when provider output cannot be translated safely."""


class ToolSelectionResolutionError(ToolSelectionServiceError):
    """Raised when one translated selection cannot be resolved or validated."""


class ToolSelectionService:
    """Compose adapter discovery, translation, and selection validation only.

    This service is a validation boundary rather than an execution engine. It
    never instantiates tools and has no executor, provider, HTTP, persistence,
    or database dependency.
    """

    def __init__(
        self,
        adapter_registry: ProviderToolCallAdapterRegistry,
        selection_resolver: ToolSelectionResolver,
    ) -> None:
        if not isinstance(adapter_registry, ProviderToolCallAdapterRegistry):
            raise TypeError(
                "adapter_registry must be a ProviderToolCallAdapterRegistry"
            )
        if not isinstance(selection_resolver, ToolSelectionResolver):
            raise TypeError("selection_resolver must be a ToolSelectionResolver")
        self._adapter_registry = adapter_registry
        self._selection_resolver = selection_resolver

    def select(
        self,
        provider_name: str,
        provider_output: object,
    ) -> ValidatedToolSelections:
        """Translate and validate calls in order, stopping at the first failure."""

        safe_provider = self._safe_provider_name(provider_name)
        try:
            adapter = self._adapter_registry.get(provider_name)
        except ProviderToolCallAdapterRegistryError as error:
            raise ToolSelectionAdapterLookupError(
                f"tool-call adapter lookup failed for provider {safe_provider!r}"
            ) from error

        try:
            requests = adapter.translate(provider_output)
        except ProviderToolCallAdapterError as error:
            raise ToolSelectionTranslationError(
                f"tool-call translation failed for provider {safe_provider!r}"
            ) from error

        validated: list[ValidatedToolSelection] = []
        resolution_errors = (
            ToolNotFoundError,
            AmbiguousToolLookupError,
            DisabledToolSelectionError,
            InvalidToolArgumentsError,
            InvalidToolSelectionRequestError,
        )
        for index, request in enumerate(requests):
            try:
                validated.append(self._selection_resolver.resolve(request))
            except resolution_errors as error:
                raise ToolSelectionResolutionError(
                    "tool selection resolution failed for "
                    f"provider {safe_provider!r} at index {index} "
                    f"with call ID {request.call_id!r}"
                ) from error

        return tuple(validated)

    @staticmethod
    def _safe_provider_name(provider_name: object) -> str:
        if not isinstance(provider_name, str):
            return "<invalid>"
        normalized = provider_name.strip().lower()
        return normalized or "<invalid>"
