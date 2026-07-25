# Model Provider Architecture

## Purpose

The provider boundary lets CX Harness request model output without depending on
Qwen, Fanar, Gemini, or any provider SDK. Stage 7.1 is entirely in memory and
does not contact an external model.

```text
Future Conversation Orchestrator
              |
              v
       ModelProvider contract
              |
      +-------+--------+
      |       |        |
    Qwen    Fanar    Gemini       (future adapters)
```

## Responsibilities

- `ModelProvider` defines generation, provider identity, model identity, and
  capability reporting.
- `ModelRequest` and `ModelResponse` keep provider inputs and outputs stable.
- `ProviderRegistry` resolves a configured provider by name and returns only
  the common interface.
- `MockModelProvider` provides deterministic offline behavior for development
  and tests.

The harness depends on `ModelProvider`, never a concrete adapter. A future
provider integrates by translating `ModelRequest` into its own API request and
translating its result back into `ModelResponse`. Authentication, HTTP clients,
streaming, prompt construction, tool calling, and orchestration remain outside
this stage.

## Current limitations

The request contract supports one text prompt and synchronous generation only.
Capabilities are declarations, not implementations. No real provider, network
transport, conversation history, token usage, streaming, or tool calling is
included yet.
