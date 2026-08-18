"""Prewarm local Ollama with the production prompt and registered tool schemas."""

from app.config.settings import settings
from app.harness.tool_loop_runtime import DEFAULT_BUSINESS_TOOL_CLASSES
from app.providers.ollama_qwen import OllamaQwenProvider
from app.tools.registry import ToolRegistry


def main() -> int:
    """Run one provider-only readiness request without business execution."""

    registry = ToolRegistry()
    for tool_class in DEFAULT_BUSINESS_TOOL_CLASSES:
        registry.register(tool_class)
    provider = OllamaQwenProvider(
        base_url=settings.ollama_base_url,
        model_name=settings.ollama_model_name,
        connect_timeout_seconds=settings.ollama_connect_timeout_seconds,
        read_timeout_seconds=settings.ollama_read_timeout_seconds,
        tool_definitions=registry.definitions(),
        max_response_bytes=settings.max_provider_response_bytes,
        context_size=settings.ollama_context_size,
        max_output_tokens=settings.ollama_max_output_tokens,
        keep_alive=settings.ollama_keep_alive,
        tool_thinking_enabled=settings.ollama_tool_thinking_enabled,
    )
    try:
        metadata = provider.prewarm()
    finally:
        provider.close()
    print("Ollama Qwen prewarm completed.")
    print(
        "Provider configuration: "
        f"thinking={metadata.thinking_enabled}, "
        f"context={metadata.context_size}, "
        f"output_cap={metadata.output_token_cap}, "
        f"timeout={metadata.timeout_seconds}s, "
        f"keep_alive={metadata.keep_alive}."
    )
    print(
        "Invocation metadata: "
        f"cache={metadata.cache_state}, "
        f"prompt_tokens={metadata.prompt_tokens}, "
        f"output_tokens={metadata.output_tokens}, "
        f"latency_ms={metadata.total_latency_ms:.3f}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
