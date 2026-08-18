import csv
import io
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.benchmark_presentation.contracts import ComparisonRequest
from app.benchmark_presentation.exports.csv_exporter import CsvZipExporter, safe_cell
from app.benchmark_presentation.exports.excel_exporter import ExcelExporter
from app.benchmark_presentation.contracts import BenchmarkCaseEvidence
from app.benchmark_presentation.exports.filenames import comparison_filename, run_filename, safe_component
from app.benchmark_presentation.exports.tables import comparison_tables, run_tables
from app.benchmark_reporting.comparison import compare_reports
from tests.benchmark_reporting.test_reporting import NOW, policy, report, snapshot


def test_comparison_request_is_frozen_and_preserves_order():
    ids = (uuid4(), uuid4())
    value = ComparisonRequest(run_ids=ids)
    assert value.run_ids == ids
    with pytest.raises(ValidationError):
        value.run_ids = tuple(reversed(ids))


@pytest.mark.parametrize("ids", [(uuid4(),), tuple(uuid4() for _ in range(9))])
def test_comparison_size_is_bounded(ids):
    with pytest.raises(ValidationError):
        ComparisonRequest(run_ids=ids)


def test_duplicate_runs_are_rejected():
    identifier = uuid4()
    with pytest.raises(ValidationError, match="duplicate"):
        ComparisonRequest(run_ids=(identifier, identifier))


@pytest.mark.parametrize("value", ["=SUM(A1:A2)", "+cmd", "-1+2", "@evil"])
def test_spreadsheet_formula_injection_is_escaped(value):
    assert safe_cell(value).startswith("'")


def test_plain_spreadsheet_cells_are_unchanged():
    assert safe_cell("qwen3:8b") == "qwen3:8b"


def test_filenames_are_utc_safe_and_have_no_path_traversal():
    assert safe_component("../../Qwen 3:8b") == "qwen-3-8b"
    assert run_filename("Qwen 3:8b", NOW, "xlsx") == "benchmark-run-qwen-3-8b-2026-07-29.xlsx"
    assert comparison_filename("CX Suite", "v1", NOW, "xlsx") == "benchmark-comparison-cx-suite-v1-2026-07-29.xlsx"


def test_run_csv_is_deterministic_and_structured():
    value = report()
    first = CsvZipExporter().render_run(value)
    assert first == CsvZipExporter().render_run(value)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist()[0] == "executive_summary.csv"
        assert "tool_performance.csv" in archive.namelist()
        rows = list(csv.DictReader(io.StringIO(archive.read("run_completion.csv").decode())))
        assert any(row["metric"] == "expected_test_cases" and row["value"] == "3" for row in rows)


def test_run_table_order_matches_workbook_contract():
    assert [name for name, _ in run_tables(report())] == [
        "Executive Summary", "Run Completion", "Quality Metrics", "Language Breakdown",
        "Category Breakdown", "Complexity Breakdown", "Pressure Breakdown", "Tool Performance",
        "Failures", "Intent Analysis", "Tokens", "Latency", "Context", "Cost", "Scoring", "Metadata",
    ]


def test_run_excel_contains_deterministic_sheet_order():
    payload = ExcelExporter().render_run(report())
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        workbook = archive.read("xl/workbook.xml").decode()
    expected = ["Executive Summary", "Model Test Evidence", "Scoring Guide"] + [name for name, _ in run_tables(report()) if name != "Executive Summary"]
    positions = [workbook.index(f'name="{name}"') for name in expected]
    assert positions == sorted(positions)


def test_run_excel_contains_native_charts_and_test_evidence_sheet():
    payload = ExcelExporter().render_run(report())
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        workbook = archive.read("xl/workbook.xml").decode()
    assert 'name="Model Test Evidence"' in workbook
    assert any(name.startswith("xl/charts/chart") for name in names)


def test_run_excel_includes_customer_question_and_model_answer():
    evidence = BenchmarkCaseEvidence(
        test_case_id="TC-001", language="egyptian_arabic", category="orders",
        customer_question="فين الأوردر؟", model="qwen3:8b",
        model_response="الأوردر في الطريق.", passed=True, hallucination=False,
        grounded=True, correct_tool=True, tool_used=("get_order_status",),
        intent_match=True, latency_ms=100, tokens=42, cost=None,
        currency_code=None, failure_category=None, failure_explanation=None,
    )
    payload = ExcelExporter().render_run(report(), (evidence,))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        strings = archive.read("xl/sharedStrings.xml").decode()
    assert "فين الأوردر؟" in strings
    assert "الأوردر في الطريق." in strings


def test_comparison_exports_include_winners_and_compatibility():
    left = report(snapshot(model="qwen", run_key="a"))
    right = report(snapshot(model="gemini", run_key="b"))
    comparison = compare_reports((left, right), policy(), NOW)
    names = [name for name, _ in comparison_tables(comparison)]
    assert "Winner Analysis" in names and "Compatibility" in names
    csv_payload = CsvZipExporter().render_comparison(comparison)
    xlsx_payload = ExcelExporter().render_comparison(comparison)
    assert csv_payload.startswith(b"PK") and xlsx_payload.startswith(b"PK")


def test_unavailable_values_are_not_rendered_as_zero():
    rows = dict(run_tables(report(snapshot(currency=False))))["Cost"]
    unavailable = next(row for row in rows if row["metric"] == "total_estimated_cost")
    assert unavailable["value"] == ""
