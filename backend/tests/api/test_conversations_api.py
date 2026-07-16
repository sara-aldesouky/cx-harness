"""Conversation API integration tests."""

from uuid import uuid4


def test_conversation_combined_filters(api_client, api_data):
    response = api_client.get(
        "/api/v1/conversations",
        params={
            "customer_id": str(api_data["customer"].id),
            "related_order_id": str(api_data["order"].id),
            "status": "open",
            "channel": "web",
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(api_data["conversation"].id)


def test_conversation_detail_and_ordered_history(api_client, api_data):
    detail = api_client.get(
        f"/api/v1/conversations/{api_data['conversation'].id}"
    )
    history = api_client.get(
        f"/api/v1/conversations/{api_data['conversation'].id}/messages"
    )

    assert detail.status_code == history.status_code == 200
    assert detail.json()["customer"]["email"] == "alpha@example.test"
    assert detail.json()["related_order"]["order_number"] == "API-ORDER-001"
    assert [message["sequence_number"] for message in detail.json()["messages"]] == [1, 2]
    assert len(detail.json()["model_runs"]) == 1
    assert [message["sequence_number"] for message in history.json()["items"]] == [1, 2]
    missing = uuid4()
    assert api_client.get(f"/api/v1/conversations/{missing}").status_code == 404
    assert (
        api_client.get(f"/api/v1/conversations/{missing}/messages").status_code
        == 404
    )
