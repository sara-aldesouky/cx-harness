# Conversation Orchestrator

## Stage 7.2 scope

The conversation orchestrator coordinates one user message with one configured
model provider while depending only on the Stage 7.1 provider contracts.

```text
User message
    |
    v
ModelRequest
    |
    v
ConversationOrchestrator -> ProviderRegistry -> ModelProvider
    |                                             |
    +------------- validated ModelResponse <------+
```

The orchestrator constructs the standardized request, resolves the configured
provider, invokes `generate()`, revalidates the response contract and provider
identity, and returns the standardized response. The current implementation is
deterministic when used with `MockModelProvider` and has no database or network
dependency.

Conversation history, context construction, prompt management, tool calling,
memory, evaluation, retries, streaming, and real provider adapters remain
future work.
