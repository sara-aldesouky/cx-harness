# Provider Prompt Adapter Contract

Stage 7.6 defines the translation boundary between the neutral prompt package
and future provider-owned formatting.

```text
PromptPackage
     |
     v
PromptAdapter.adapt()
     |
validate -> provider translation hook -> revalidate
     |
     v
ProviderRequest
```

The template-method interface validates both sides of translation and confirms
that translated provider/model identity matches the selected adapter. Concrete
adapters implement only `_translate()`. `MockPromptAdapter` demonstrates the
complete contract with deterministic copying and no external dependency.

`ProviderRequest` remains an internal standardized representation rather than
an HTTP, SDK, ChatML, Gemini, OpenAI, Ollama, Qwen, or Fanar payload. Real
provider formatting, authentication, transport, invocation, streaming, token
handling, tools, memory, and persistence are intentionally excluded.
