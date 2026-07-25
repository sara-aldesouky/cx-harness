# Model Pipeline Service Integration Verification

Stage 7.11 provides one explicitly enabled integration test that exercises the
complete application boundary with local infrastructure only:

```text
ModelPipelineService -> ContextBuilder -> runtime coordinator -> PromptManager
  -> OllamaPromptAdapter -> OllamaQwenProvider -> local qwen3:8b
  -> ModelPipelineServiceResult -> ModelRunAuditRepository
  -> Docker PostgreSQL
```

The test uses the guarded `DATABASE_URL_TEST`, creates one disposable customer
and conversation, invokes the real local model, verifies exactly one completed
`ModelRun`, and deletes all disposable rows in a `finally` block. It never uses
`DATABASE_URL` and cannot target Render through the test fixture guard.

Run it explicitly from `backend/` while Ollama and Docker PostgreSQL are ready:

```bash
RUN_OLLAMA_INTEGRATION=1 .venv/bin/python -m pytest \
  -o addopts='' -q -m live_model \
  tests/services/integration/test_model_pipeline_service_live.py
```
