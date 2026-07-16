"""Tool-call API integration tests."""

from uuid import uuid4

from tests.models.factories import create_tool_call


def test_empty_tool_call_list_and_missing_detail(api_client):
    response = api_client.get(
        "/api/v1/tool-calls", params={"limit": 10, "offset": 0}
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 10, "offset": 0}
    assert api_client.get(f"/api/v1/tool-calls/{uuid4()}").status_code == 404


def test_tool_call_filters_and_json_serialization(api_client, api_session, api_data):
    tool_call = create_tool_call(api_session, api_data["model_run"])

    response = api_client.get(
        "/api/v1/tool-calls",
        params={
            "model_run_id": str(api_data["model_run"].id),
            "tool_name": "get_order_status",
            "status": "completed",
            "success": "true",
        },
    )
    detail = api_client.get(f"/api/v1/tool-calls/{tool_call.id}")

    assert response.status_code == detail.status_code == 200
    assert response.json()["total"] == 1
    assert detail.json()["input_json"] == {"order_id": "TEST-ORDER"}
    assert detail.json()["output_json"] == {"status": "preparing"}
