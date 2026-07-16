"""Order-item API integration tests."""

from uuid import uuid4


def test_order_item_filters_and_detail(api_client, api_data):
    response = api_client.get(
        "/api/v1/order-items",
        params={
            "order_id": str(api_data["order"].id),
            "item_status": "included",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(api_data["item"].id)
    detail = api_client.get(f"/api/v1/order-items/{api_data['item'].id}")
    assert detail.status_code == 200
    assert detail.json()["unit_price"] == "12.50"
    assert api_client.get(f"/api/v1/order-items/{uuid4()}").status_code == 404
