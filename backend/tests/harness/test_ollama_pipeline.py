"""Offline tests for the Stage 7.7 Ollama/Qwen pipeline."""

from __future__ import annotations

import json

import httpx
import pytest

from app.harness import (
    DuplicatePromptAdapterRegistrationError,
    MockPromptAdapter,
    ModelPipelineCoordinator,
    OllamaPromptAdapter,
    PipelineIdentityMismatchError,
    PromptAdapterNotFoundError,
    PromptAdapterRegistry,
)
from app.providers.ollama_qwen import (
    EmptyModelResponseError,
    InvalidOllamaResponseError,
    OllamaQwenProvider,
    OllamaRequestTimeoutError,
    OllamaUnavailableError,
)
from app.providers.registry import ProviderNotFoundError, ProviderRegistry


def make_coordinator(
    handler: httpx.MockTransport,
    *,
    adapter_model: str = "qwen3:8b",
    provider_model: str = "qwen3:8b",
) -> ModelPipelineCoordinator:
    client = httpx.Client(transport=handler)
    provider = OllamaQwenProvider(
        model_name=provider_model,
        client=client,
        connect_timeout_seconds=0.5,
        read_timeout_seconds=1.0,
    )
    provider_registry = ProviderRegistry()
    provider_registry.register(provider)
    adapter_registry = PromptAdapterRegistry()
    adapter_registry.register(OllamaPromptAdapter(model_name=adapter_model))
    return ModelPipelineCoordinator(
        provider_registry=provider_registry,
        adapter_registry=adapter_registry,
    )


def run_pipeline(coordinator: ModelPipelineCoordinator):
    return coordinator.run(
        system_instructions="  Be concise.  ",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
        provider_name="ollama",
        model_name="qwen3:8b",
    )


def test_successful_full_pipeline_and_exact_ollama_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "  Done.  "}},
        )

    response = run_pipeline(make_coordinator(httpx.MockTransport(handler)))

    assert response.content == "Done."
    assert response.provider_name == "ollama"
    assert response.model_name == "qwen3:8b"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"] == {
        "model": "qwen3:8b",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
        "stream": False,
    }


def test_pipeline_is_deterministic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "same"}}
        )

    coordinator = make_coordinator(httpx.MockTransport(handler))
    assert run_pipeline(coordinator) == run_pipeline(coordinator)


def test_ollama_unavailable_is_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    with pytest.raises(OllamaUnavailableError):
        run_pipeline(make_coordinator(httpx.MockTransport(handler)))


def test_ollama_timeout_is_domain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(OllamaRequestTimeoutError):
        run_pipeline(make_coordinator(httpx.MockTransport(handler)))


def test_invalid_json_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(InvalidOllamaResponseError, match="invalid JSON"):
        run_pipeline(make_coordinator(httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"message": "wrong"},
        {"message": {"role": "user", "content": "wrong role"}},
        {"message": {"role": "assistant", "content": 123}},
    ],
)
def test_malformed_or_unsupported_response_is_rejected(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(InvalidOllamaResponseError):
        run_pipeline(make_coordinator(httpx.MockTransport(handler)))


@pytest.mark.parametrize("content", ["", "   "])
def test_empty_model_response_is_rejected(content: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": content}},
        )

    with pytest.raises(EmptyModelResponseError):
        run_pipeline(make_coordinator(httpx.MockTransport(handler)))


def test_provider_adapter_model_mismatch_is_rejected_before_http() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    coordinator = make_coordinator(
        httpx.MockTransport(handler), adapter_model="qwen3:4b"
    )
    with pytest.raises(PipelineIdentityMismatchError, match="model names"):
        run_pipeline(coordinator)
    assert calls == 0


def test_unknown_adapter_and_provider_fail_clearly() -> None:
    empty_adapters = PromptAdapterRegistry()
    providers = ProviderRegistry()
    providers.register(OllamaQwenProvider())
    coordinator = ModelPipelineCoordinator(
        provider_registry=providers, adapter_registry=empty_adapters
    )
    with pytest.raises(PromptAdapterNotFoundError):
        run_pipeline(coordinator)

    adapters = PromptAdapterRegistry()
    adapters.register(OllamaPromptAdapter())
    coordinator = ModelPipelineCoordinator(
        provider_registry=ProviderRegistry(), adapter_registry=adapters
    )
    with pytest.raises(ProviderNotFoundError):
        run_pipeline(coordinator)


def test_adapter_registry_is_deterministic_and_rejects_duplicates() -> None:
    registry = PromptAdapterRegistry()
    ollama = OllamaPromptAdapter()
    mock = MockPromptAdapter()
    registry.register(ollama)
    registry.register(mock)

    assert registry.get(" OLLAMA ") is ollama
    assert tuple(adapter.provider_name for adapter in registry.list()) == (
        "mock",
        "ollama",
    )
    assert registry.list() == registry.list()
    with pytest.raises(DuplicatePromptAdapterRegistrationError):
        registry.register(OllamaPromptAdapter())


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com",
        "http://user:password@localhost:11434",
        "ftp://localhost:11434",
    ],
)
def test_provider_rejects_nonlocal_or_credentialed_urls(base_url: str) -> None:
    with pytest.raises(ValueError):
        OllamaQwenProvider(base_url=base_url)


def test_unit_pipeline_has_no_database_dependency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": "ok"}}
        )

    coordinator = make_coordinator(httpx.MockTransport(handler))
    assert coordinator._model_run_audit_repository is None
    assert not hasattr(coordinator, "database_session")
    assert not hasattr(coordinator, "database_engine")
    assert run_pipeline(coordinator).content == "ok"
