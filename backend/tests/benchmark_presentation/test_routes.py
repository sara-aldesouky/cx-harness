from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_db_session
from app.benchmark_presentation.contracts import BenchmarkRunPage
from app.benchmark_reporting.comparison import compare_reports
from app.main import app
from tests.benchmark_reporting.test_reporting import NOW, policy, report, snapshot


@pytest.fixture
def api_client(db_session):
    def session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_db_session, None)


def test_reporting_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/v1/benchmark-reporting/runs" in paths
    assert "/api/v1/benchmark-reporting/comparisons" in paths
    assert "/api/v1/benchmark-reporting/runs/{run_id}/export.xlsx" in paths


def test_list_validation_rejects_unbounded_pagination(api_client):
    response = api_client.get("/api/v1/benchmark-reporting/runs?limit=101")
    assert response.status_code == 422


def test_comparison_validation_rejects_duplicates(api_client):
    identifier = str(uuid4())
    response = api_client.post("/api/v1/benchmark-reporting/comparisons", json={"run_ids": [identifier, identifier]})
    assert response.status_code == 422


def test_invalid_date_range_returns_stable_error(api_client):
    response = api_client.get("/api/v1/benchmark-reporting/runs?created_from=2026-08-01T00:00:00Z&created_to=2026-07-01T00:00:00Z")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_date_filter"


def test_unknown_run_returns_safe_error(api_client):
    response = api_client.get(f"/api/v1/benchmark-reporting/runs/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"code": "benchmark_run_not_found", "message": "The benchmark run was not found.", "details": []}


class FakePresentationService:
    def __init__(self, _session):
        self.left = report(snapshot(model="qwen", run_key="run-a"))
        self.right = report(snapshot(model="gemini", run_key="run-b"))

    def get_report(self, _run_id):
        return self.left

    def get_case_evidence(self, _run_id):
        return ()

    def policy(self, _key, _version):
        return policy()

    def compare(self, _run_ids, _policy):
        return compare_reports((self.left, self.right), policy(), NOW)


def test_report_comparison_and_exports_are_read_only(api_client, db_session, monkeypatch):
    from app.api.routes import benchmark_reporting

    monkeypatch.setattr(benchmark_reporting, "BenchmarkPresentationService", FakePresentationService)
    identifier = uuid4()
    report_response = api_client.get(f"/api/v1/benchmark-reporting/runs/{identifier}")
    comparison_response = api_client.post(
        "/api/v1/benchmark-reporting/comparisons",
        json={"run_ids": [str(uuid4()), str(uuid4())]},
    )
    csv_response = api_client.get(f"/api/v1/benchmark-reporting/runs/{identifier}/export.csv")
    excel_response = api_client.get(f"/api/v1/benchmark-reporting/runs/{identifier}/export.xlsx")
    assert report_response.status_code == comparison_response.status_code == 200
    assert report_response.json()["completion"]["expected_test_cases"] == 3
    assert comparison_response.json()["runs"][0]["suite_key"] == "suite"
    assert csv_response.headers["content-type"] == "application/zip"
    assert csv_response.content.startswith(b"PK")
    assert "benchmark-run-qwen-2026-07-29.csv.zip" in csv_response.headers["content-disposition"]
    assert excel_response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert excel_response.content.startswith(b"PK")
    assert not db_session.new and not db_session.dirty and not db_session.deleted
