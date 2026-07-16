"""Model-run API integration tests."""

from decimal import Decimal
from uuid import uuid4

from tests.models.factories import create_evaluation, create_tool_call


def test_model_run_combined_filters_and_pagination(api_client, api_data):
    response = api_client.get(
        "/api/v1/model-runs",
        params={
            "conversation_id": str(api_data["conversation"].id),
            "provider": "gemini",
            "model_name": "gemini-2.0-flash",
            "status": "completed",
            "success": "true",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(api_data["model_run"].id)
    assert body["items"][0]["estimated_cost"] == "0.001000"


def test_model_run_detail_and_nested_resources(
    api_client, api_session, api_data
):
    tool_call = create_tool_call(api_session, api_data["model_run"])
    evaluation = create_evaluation(
        api_session,
        api_data["model_run"],
        overall_score=Decimal("4.50"),
        details_json={"source": "api-test"},
    )

    detail = api_client.get(f"/api/v1/model-runs/{api_data['model_run'].id}")
    tools = api_client.get(
        f"/api/v1/model-runs/{api_data['model_run'].id}/tool-calls"
    )
    evaluations = api_client.get(
        f"/api/v1/model-runs/{api_data['model_run'].id}/evaluations"
    )

    assert detail.status_code == tools.status_code == evaluations.status_code == 200
    assert detail.json()["tool_calls"][0]["id"] == str(tool_call.id)
    assert detail.json()["evaluations"][0]["id"] == str(evaluation.id)
    assert tools.json()["total"] == 1
    assert evaluations.json()["total"] == 1
    missing = uuid4()
    assert api_client.get(f"/api/v1/model-runs/{missing}").status_code == 404
    assert (
        api_client.get(f"/api/v1/model-runs/{missing}/tool-calls").status_code
        == 404
    )
    assert (
        api_client.get(f"/api/v1/model-runs/{missing}/evaluations").status_code
        == 404
    )
