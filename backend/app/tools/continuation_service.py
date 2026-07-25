"""Provider-neutral orchestration for one continuation translation."""

from __future__ import annotations

from app.tools.continuation_adapter import (
    ProviderContinuationAdapterError,
    ProviderContinuationPayload,
)
from app.tools.continuation_adapter_registry import (
    ProviderContinuationAdapterRegistry,
    ProviderContinuationAdapterRegistryError,
)
from app.tools.execution_outcome import ToolExecutionOutcome


class ProviderContinuationServiceError(Exception):
    """Base error for continuation translation orchestration failures."""


class ProviderContinuationAdapterLookupError(ProviderContinuationServiceError):
    """Raised when a continuation adapter cannot be resolved safely."""


class ProviderContinuationTranslationError(ProviderContinuationServiceError):
    """Raised when an adapter cannot translate a valid tool outcome."""


class InvalidProviderContinuationPayloadError(ProviderContinuationServiceError):
    """Raised when an adapter returns something other than the payload contract."""


class ProviderContinuationPayloadMismatchError(ProviderContinuationServiceError):
    """Raised when returned provider or call correlation does not match."""


class ProviderContinuationService:
    """Resolve one adapter and translate exactly one completed tool outcome.

    The service coordinates discovery and contract verification only. It does
    not execute tools, invoke providers, generate prompts, or persist data.
    """

    def __init__(
        self,
        adapter_registry: ProviderContinuationAdapterRegistry,
    ) -> None:
        if not isinstance(adapter_registry, ProviderContinuationAdapterRegistry):
            raise TypeError(
                "adapter_registry must be a ProviderContinuationAdapterRegistry"
            )
        self._adapter_registry = adapter_registry

    def translate(
        self,
        provider_name: str,
        outcome: ToolExecutionOutcome,
    ) -> ProviderContinuationPayload:
        """Return one verified adapter payload without copying or mutation."""

        if not isinstance(outcome, ToolExecutionOutcome):
            raise ProviderContinuationTranslationError(
                "continuation translation requires a ToolExecutionOutcome"
            )

        safe_provider = self._safe_provider_name(provider_name)
        try:
            adapter = self._adapter_registry.get(provider_name)
        except ProviderContinuationAdapterRegistryError as error:
            raise ProviderContinuationAdapterLookupError(
                f"continuation adapter lookup failed for provider {safe_provider!r}"
            ) from error

        try:
            payload = adapter.translate(outcome)
        except ProviderContinuationAdapterError as error:
            raise ProviderContinuationTranslationError(
                "continuation translation failed for "
                f"provider {safe_provider!r} and call ID {outcome.call_id!r}"
            ) from error

        if not isinstance(payload, ProviderContinuationPayload):
            raise InvalidProviderContinuationPayloadError(
                "continuation adapter returned an invalid payload for "
                f"provider {safe_provider!r} and call ID {outcome.call_id!r}"
            )
        if payload.provider_name != safe_provider:
            raise ProviderContinuationPayloadMismatchError(
                "continuation payload provider does not match resolved provider "
                f"{safe_provider!r} for call ID {outcome.call_id!r}"
            )
        if payload.call_id != outcome.call_id:
            raise ProviderContinuationPayloadMismatchError(
                "continuation payload call ID does not match outcome call ID "
                f"{outcome.call_id!r} for provider {safe_provider!r}"
            )
        return payload

    @staticmethod
    def _safe_provider_name(provider_name: object) -> str:
        if not isinstance(provider_name, str):
            return "<invalid>"
        normalized = provider_name.strip().lower()
        return normalized or "<invalid>"
