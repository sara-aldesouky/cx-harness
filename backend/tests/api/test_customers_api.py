"""Customer API integration tests."""

from uuid import uuid4


def test_customer_list_pagination_and_ordering(api_client, api_data):
    response = api_client.get("/api/v1/customers", params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["items"][0]["id"] == str(api_data["customer"].id)
    assert api_client.get("/api/v1/customers", params={"limit": 1}).json() == body


def test_customer_detail_and_missing(api_client, api_data):
    response = api_client.get(f"/api/v1/customers/{api_data['customer'].id}")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alpha@example.test"
    assert [order["order_number"] for order in body["orders"]] == ["API-ORDER-001"]
    assert len(body["conversations"]) == 1
    assert api_client.get(f"/api/v1/customers/{uuid4()}").status_code == 404
