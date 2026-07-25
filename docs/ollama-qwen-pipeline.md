# Ollama/Qwen End-to-End Pipeline

Stage 7.7 connects the existing provider-neutral contracts to the first real,
local model integration.

```text
Trusted inputs -> ContextBuilder -> PromptManager -> PromptAdapterRegistry
  -> OllamaPromptAdapter -> OllamaProviderRequest -> ProviderRegistry
  -> ModelProvider.generate_provider_request() -> local Ollama/Qwen
  -> ModelResponse
```

## Contract bridge decision

`ModelProvider.generate(ModelRequest)` remains unchanged for compatibility.
Stage 7.7 adds an opt-in `generate_provider_request(ProviderRequest)` method to
the same interface. Providers that support structured prompt adapters override
it; unsupported providers fail explicitly. This avoids flattening structured
messages back into text and keeps the coordinator dependent on `ModelProvider`
rather than `OllamaQwenProvider`.

The adapter owns role translation but performs no I/O. The provider owns local
HTTP transport and response parsing. The coordinator knows only registries and
interfaces. Ollama URLs are restricted to localhost, credentials are rejected,
timeouts are explicit, streaming is disabled, and raw provider payloads never
cross the `ModelResponse` boundary.

Run the optional local check explicitly from `backend/`:

```bash
.venv/bin/python -m scripts.smoke_test_ollama_qwen
```

The command skips cleanly when Ollama or the configured Qwen model is absent.
