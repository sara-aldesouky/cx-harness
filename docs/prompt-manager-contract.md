# Prompt Manager Contract

Stage 7.5 defines the neutral prompt boundary between completed conversation
context and future provider adapters.

```text
ConversationContext
        |
        v
  PromptManager
        |
  revalidate + copy
        |
        v
   PromptPackage
        |
        v
Future provider adapter formatting
```

`PromptMessage` preserves the shared role, normalized content, and immutable
metadata semantics. `PromptPackage` contains system instructions, ordered
messages, and optional provider/model routing labels. `PromptManager` is
stateless and defensively copies a revalidated context into these contracts.

The output is not ChatML, Gemini, OpenAI, Ollama, Qwen, or Fanar format. Future
adapters will translate the neutral package into their own payloads. Prompt
engineering, token handling, truncation, retrieval, tools, model invocation,
networking, and persistence are intentionally absent.
