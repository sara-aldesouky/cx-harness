"""Explicit local smoke test for the Ollama/Qwen model pipeline."""

from __future__ import annotations

from app.config.settings import settings
from app.harness import (
    ModelPipelineCoordinator,
    OllamaPromptAdapter,
    PromptAdapterRegistry,
)
from app.providers.ollama_qwen import OllamaProviderError, OllamaQwenProvider
from app.providers.registry import ProviderRegistry


def main() -> int:
    """Run one explicitly requested local prompt, or skip cleanly if unavailable."""

    provider = OllamaQwenProvider(
        base_url=settings.ollama_base_url,
        model_name=settings.ollama_model_name,
        connect_timeout_seconds=settings.ollama_connect_timeout_seconds,
        read_timeout_seconds=settings.ollama_read_timeout_seconds,
    )
    adapter = OllamaPromptAdapter(model_name=settings.ollama_model_name)
    provider_registry = ProviderRegistry()
    provider_registry.register(provider)
    adapter_registry = PromptAdapterRegistry()
    adapter_registry.register(adapter)
    coordinator = ModelPipelineCoordinator(
        provider_registry=provider_registry,
        adapter_registry=adapter_registry,
    )

    try:
        response = coordinator.run(
            system_instructions="Reply in one short sentence.",
            messages=[
                {"role": "user", "content": "What is customer service?"}
            ],
            provider_name=provider.provider_name,
            model_name=provider.model_name,
        )
    except OllamaProviderError as exc:
        print(f"SKIPPED: {exc}")
        return 0

    print(response.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
