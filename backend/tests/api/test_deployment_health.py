"""Production deployment boundary tests without database or provider access."""

from app.config.settings import Settings


def test_health_check_is_dependency_free(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "cx-harness-api"}


def test_local_cors_preflight_is_narrow_and_supported(api_client):
    response = api_client.options(
        "/api/v1/benchmark-reporting/runs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_cors_origins_are_normalized_deduplicated_and_explicit():
    configured = Settings(
        cors_allowed_origins=(
            "http://localhost:3000/, https://dashboard.example.com,"
            "https://dashboard.example.com/"
        )
    )

    assert configured.allowed_cors_origins == (
        "http://localhost:3000",
        "https://dashboard.example.com",
    )


def test_cors_wildcard_and_malformed_origins_fail_closed():
    for value in ("*", "", "dashboard.example.com", "https://user:secret@example.com"):
        configured = Settings(cors_allowed_origins=value)
        try:
            configured.allowed_cors_origins
        except ValueError as error:
            assert "CORS_ALLOWED_ORIGINS" in str(error)
        else:
            raise AssertionError(f"unsafe CORS origin was accepted: {value!r}")
