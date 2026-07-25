# Model Invocation FastAPI Endpoint

Stage 7.13 adds one thin synchronous transport boundary:

```text
POST /api/v1/model/invoke
  -> ModelInvocationRequest
  -> injected ModelInvocationMapper
  -> ModelPipelineService
  -> ModelInvocationResponse
```

The cached dependency contains a side-effect-free service whose runtime pipeline
is still constructed lazily per invocation. The route creates no provider,
registry, SQLAlchemy session, context, or prompt. It performs no retries.

Public errors use `APIErrorResponse` with stable codes and safe messages. Input
validation remains FastAPI's standard 422 response; application input maps to
400, unavailable startup/provider dependencies to 503, malformed provider output
to 502, persistence failure to 500, and unexpected errors to a generic 500. No
exception text, stack trace, database URL, or transport payload is returned.

There is no 404 mapping in this stage because the existing application service
does not retrieve conversations and exposes no resource-not-found exception.
