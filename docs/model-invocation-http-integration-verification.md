# Model Invocation HTTP Integration Verification

Stage 7.14 provides one explicitly enabled full-stack HTTP verification using
only local infrastructure:

```text
TestClient -> POST /api/v1/model/invoke -> real FastAPI dependency
  -> ModelInvocationMapper -> ModelPipelineService -> runtime coordinator
  -> local Ollama/qwen3:8b -> ModelRunAuditRepository -> Docker PostgreSQL
  -> HTTP 200 ModelInvocationResponse
```

The test uses the guarded `DATABASE_URL_TEST` and overrides only the composition
dependency with real objects configured for that local database. It creates one
disposable customer and conversation, verifies exactly one completed ModelRun,
then removes the conversation, cascaded ModelRun, and customer in `finally`.

Run explicitly from `backend/`:

```bash
RUN_HTTP_OLLAMA_INTEGRATION=1 .venv/bin/python -m pytest \
  -o addopts='' -q -s -m live_http_model \
  tests/api/integration/test_model_invocation_http_live.py
```
