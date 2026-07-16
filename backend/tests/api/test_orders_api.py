"""Order API integration tests."""

from uuid import uuid4


def test_order_list_combined_filters_and_pagination(api_client, api_data):
    params = {
        "customer_id": str(api_data["customer"].id),
        "status": "delivered",
        "payment_status": "paid",
        "limit": 1,
        "offset": 0,
    }
    response = api_client.get("/api/v1/orders", params=params)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["order_number"] == "API-ORDER-001"
    assert body["items"][0]["total_amount"] == "25.00"


def test_order_detail_and_number_lookup(api_client, api_data):
    by_id = api_client.get(f"/api/v1/orders/{api_data['order'].id}")
    by_number = api_client.get("/api/v1/orders/by-number/API-ORDER-001")

    assert by_id.status_code == by_number.status_code == 200
    assert by_id.json() == by_number.json()
    assert by_id.json()["customer"]["email"] == "alpha@example.test"
    assert len(by_id.json()["items"]) == 1
    assert len(by_id.json()["conversations"]) == 1
    assert api_client.get(f"/api/v1/orders/{uuid4()}").status_code == 404
    assert api_client.get("/api/v1/orders/by-number/MISSING").status_code == 404
