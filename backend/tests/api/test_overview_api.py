"""Overview and read-only behavior integration tests."""

from tests.repositories.conftest import table_counts


def test_overview_matches_live_transaction_counts(api_client, api_session, api_data):
    response = api_client.get("/api/v1/overview")

    assert response.status_code == 200
    assert response.json() == {
        "customers": 2,
        "orders": 2,
        "order_items": 2,
        "conversations": 2,
        "messages": 3,
        "model_runs": 2,
        "tool_calls": 0,
        "evaluations": 0,
    }
    assert response.json() == table_counts(api_session)


def test_all_list_endpoints_are_read_only(api_client, api_session, api_data):
    before = table_counts(api_session)
    paths = [
        "/api/v1/overview",
        "/api/v1/customers",
        "/api/v1/orders",
        "/api/v1/order-items",
        "/api/v1/conversations",
        "/api/v1/messages",
        "/api/v1/model-runs",
        "/api/v1/tool-calls",
        "/api/v1/evaluations",
    ]

    for path in paths:
        assert api_client.get(path).status_code == 200

    api_session.expire_all()
    assert table_counts(api_session) == before
