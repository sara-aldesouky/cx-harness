# Single Model Continuation Invocation

Stage 8.16 adds the terminal model boundary after one completed tool cycle.

```text
ToolContinuationCycle + original ConversationContext + model identity
                              |
                              v
               SingleModelContinuationService
                              |
                              v
                    ProviderRegistry
                              |
                              v
             ModelProvider.continue_model(request)
                              |
                              v
                 terminal ModelResponse
```

The service begins with a completed cycle because selection, trusted execution,
tool auditing, outcome correlation, and continuation-payload translation must
already be finished. Provider and model identities must match the cycle, payload,
context, resolved provider, and final response; Stage 8 permits neither provider
handoff nor model routing.

`ModelContinuationRequest` is an immutable neutral envelope containing the
original typed conversation context and the existing continuation payload.
Concrete providers own conversion of that payload into provider-native tool-result
messages, transport calls, and response parsing. The application service performs
no Ollama, Gemini, OpenAI, or prompt formatting.

Each invocation performs one provider lookup, creates one request, and calls one
provider continuation method. It never retries, falls back, selects a tool, or
re-executes the completed cycle. One valid canonical `ModelResponse` is returned
as the original provider-created instance.

The current canonical response is terminal text. Provider response extensions
that expose another tool call or a tool-call finish reason are rejected instead
of starting a second cycle. That explicit boundary keeps Stage 8 free of an agent
loop; repeated tool/model turns belong to Stage 9.

Tool auditing remains exclusively owned by `ToolExecutor`. Existing model-run
persistence is currently owned by `ModelPipelineCoordinator`, whose prompt-based
request contract does not accept continuation payloads. This service does not
duplicate persistence; integrating continuation requests with that audit boundary
requires a later explicit composition stage.
