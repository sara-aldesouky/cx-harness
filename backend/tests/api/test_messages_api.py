"""Message API integration tests."""

from uuid import uuid4


def test_message_combined_filters_pagination_and_detail(api_client, api_data):
    response = api_client.get(
        "/api/v1/messages",
        params={
            "conversation_id": str(api_data["conversation"].id),
            "role": "assistant",
            "language": "mixed",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert body["items"][0]["id"] == str(api_data["second_message"].id)
    assert body["items"][0]["language"] == "mixed"
    detail = api_client.get(f"/api/v1/messages/{api_data['first_message'].id}")
    assert detail.status_code == 200
    assert detail.json()["created_at"].endswith(("Z", "+00:00"))
    assert api_client.get(f"/api/v1/messages/{uuid4()}").status_code == 404
