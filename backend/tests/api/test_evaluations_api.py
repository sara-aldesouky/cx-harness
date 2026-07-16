"""Evaluation API integration tests."""

from decimal import Decimal
from uuid import uuid4

from tests.models.factories import create_evaluation


def test_empty_evaluation_list_and_missing_detail(api_client):
    response = api_client.get(
        "/api/v1/evaluations", params={"limit": 10, "offset": 0}
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 10, "offset": 0}
    assert api_client.get(f"/api/v1/evaluations/{uuid4()}").status_code == 404


def test_evaluation_filters_decimal_nullable_and_json(
    api_client, api_session, api_data
):
    evaluation = create_evaluation(
        api_session,
        api_data["model_run"],
        evaluator_type="human",
        evaluator_name="manager_review",
        overall_score=Decimal("4.25"),
        tone_score=None,
        details_json={"reviewer": "synthetic"},
    )

    response = api_client.get(
        "/api/v1/evaluations",
        params={
            "model_run_id": str(api_data["model_run"].id),
            "evaluator_type": "human",
            "evaluator_name": "manager_review",
            "passed": "true",
            "minimum_score": "4",
            "maximum_score": "4.5",
        },
    )
    detail = api_client.get(f"/api/v1/evaluations/{evaluation.id}")

    assert response.status_code == detail.status_code == 200
    assert response.json()["total"] == 1
    assert detail.json()["overall_score"] == "4.25"
    assert detail.json()["tone_score"] is None
    assert detail.json()["details_json"] == {"reviewer": "synthetic"}
