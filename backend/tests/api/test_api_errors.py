"""API validation and OpenAPI integration tests."""

from uuid import uuid4


def test_invalid_uuid_pagination_and_boolean_return_422(api_client):
    assert api_client.get("/api/v1/customers/not-a-uuid").status_code == 422
    assert api_client.get("/api/v1/customers", params={"limit": 0}).status_code == 422
    assert (
        api_client.get("/api/v1/orders", params={"offset": -1}).status_code == 422
    )
    assert (
        api_client.get("/api/v1/model-runs", params={"success": "maybe"}).status_code
        == 422
    )


def test_repository_validation_errors_are_safe_422_responses(api_client):
    cases = [
        ("/api/v1/orders", {"status": "unknown"}),
        ("/api/v1/order-items", {"item_status": "unknown"}),
        ("/api/v1/conversations", {"channel": "email"}),
        ("/api/v1/messages", {"role": "agent"}),
        ("/api/v1/model-runs", {"provider": "openai"}),
        ("/api/v1/tool-calls", {"status": "unknown"}),
        ("/api/v1/evaluations", {"evaluator_type": "external"}),
        (
            "/api/v1/evaluations",
            {"minimum_score": "5", "maximum_score": "1"},
        ),
    ]

    for path, params in cases:
        response = api_client.get(path, params=params)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
        assert "postgresql://" not in response.text
        assert "SELECT " not in response.text


def test_openapi_and_docs_expose_exact_read_only_surface(api_client):
    docs = api_client.get("/docs")
    openapi = api_client.get("/openapi.json")

    assert docs.status_code == openapi.status_code == 200
    schema = openapi.json()
    assert len(schema["paths"]) == 21
    assert {
        method
        for operations in schema["paths"].values()
        for method in operations
    } == {"get"}
    assert {
        tag
        for operations in schema["paths"].values()
        for operation in operations.values()
        for tag in operation["tags"]
    } == {
        "Customers",
        "Orders",
        "Order Items",
        "Conversations",
        "Messages",
        "Model Runs",
        "Tool Calls",
        "Evaluations",
        "Overview",
    }
    assert "/api/v1/orders/by-number/{order_number}" in schema["paths"]
    assert f"/api/v1/customers/{uuid4()}" not in schema["paths"]
