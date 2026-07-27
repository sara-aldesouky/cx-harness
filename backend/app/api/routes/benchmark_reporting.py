"""Read-only benchmark reporting, comparison, and export routes."""

from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.benchmark_presentation.contracts import BenchmarkRunPage, ComparisonRequest, PresentationError
from app.benchmark_presentation.errors import BenchmarkPresentationError, ExportGenerationError
from app.benchmark_presentation.exports import CsvZipExporter, ExcelExporter
from app.benchmark_presentation.exports.filenames import comparison_filename, run_filename
from app.benchmark_presentation.service import BenchmarkPresentationService
from app.benchmark_reporting.contracts import BenchmarkRunReport, ModelComparisonReport
from app.benchmark_reporting.errors import IncompatibleComparisonError, RunNotFoundError

router = APIRouter(prefix="/benchmark-reporting", tags=["Benchmark Reporting"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


def _error(error: Exception) -> Response:
    if isinstance(error, RunNotFoundError):
        status, code, message, details = 404, "benchmark_run_not_found", "The benchmark run was not found.", ()
    elif isinstance(error, IncompatibleComparisonError):
        status, code, message, details = 409, "comparison_incompatible", "The selected runs cannot be compared.", (str(error),)
    elif isinstance(error, BenchmarkPresentationError):
        status, code, message, details = error.status_code, error.code, error.public_message, error.details
    else:
        status, code, message, details = 500, "report_generation_failed", "The benchmark report could not be generated.", ()
    body = PresentationError(code=code, message=message, details=details).model_dump_json()
    return Response(body, status_code=status, media_type="application/json")


@router.get("/runs", response_model=BenchmarkRunPage, summary="List benchmark runs")
def list_runs(
    session: SessionDependency,
    suite_key: Optional[str] = None,
    suite_version: Optional[str] = None,
    model_name: Optional[str] = None,
    provider_name: Optional[str] = None,
    status: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if created_from and created_to and created_from > created_to:
        return Response(
            PresentationError(code="invalid_date_filter", message="created-from must not be later than created-to").model_dump_json(),
            status_code=400,
            media_type="application/json",
        )
    try:
        return BenchmarkPresentationService(session).list_runs(
            suite_key=suite_key,
            suite_version=suite_version,
            model_name=model_name,
            provider_name=provider_name,
            status=status,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        return _error(error)


@router.get("/runs/{run_id}", response_model=BenchmarkRunReport, summary="Get a benchmark report")
def get_run_report(run_id: UUID, session: SessionDependency):
    try:
        return BenchmarkPresentationService(session).get_report(run_id)
    except Exception as error:
        return _error(error)


@router.post("/comparisons", response_model=ModelComparisonReport, summary="Compare benchmark runs")
def compare_runs(request: ComparisonRequest, session: SessionDependency):
    try:
        service = BenchmarkPresentationService(session)
        return service.compare(request.run_ids, service.policy(request.scoring_policy_key, request.scoring_policy_version))
    except Exception as error:
        return _error(error)


def _download(payload: bytes, media_type: str, filename: str) -> Response:
    return Response(
        payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/runs/{run_id}/export.csv", summary="Export a benchmark run as CSV ZIP")
def export_run_csv(run_id: UUID, session: SessionDependency):
    try:
        report = BenchmarkPresentationService(session).get_report(run_id)
        return _download(CsvZipExporter().render_run(report), CsvZipExporter.media_type, run_filename(report.run.model_name, report.run.created_at, "csv.zip"))
    except Exception as error:
        return _error(error if isinstance(error, (RunNotFoundError, BenchmarkPresentationError)) else ExportGenerationError())


@router.get("/runs/{run_id}/export.xlsx", summary="Export a benchmark run as Excel")
def export_run_excel(run_id: UUID, session: SessionDependency):
    try:
        service = BenchmarkPresentationService(session)
        report = service.get_report(run_id)
        evidence = service.get_case_evidence(run_id)
        return _download(ExcelExporter().render_run(report, evidence), ExcelExporter.media_type, run_filename(report.run.model_name, report.run.created_at, "xlsx"))
    except Exception as error:
        return _error(error if isinstance(error, (RunNotFoundError, BenchmarkPresentationError)) else ExportGenerationError())


def _comparison_export(request: ComparisonRequest, session: Session, excel: bool):
    try:
        service = BenchmarkPresentationService(session)
        report = service.compare(request.run_ids, service.policy(request.scoring_policy_key, request.scoring_policy_version))
        if excel:
            return _download(ExcelExporter().render_comparison(report), ExcelExporter.media_type, comparison_filename(report.suite_key, report.suite_version, report.generated_at, "xlsx"))
        return _download(CsvZipExporter().render_comparison(report), CsvZipExporter.media_type, comparison_filename(report.suite_key, report.suite_version, report.generated_at, "csv.zip"))
    except Exception as error:
        recognized = (RunNotFoundError, IncompatibleComparisonError, BenchmarkPresentationError)
        return _error(error if isinstance(error, recognized) else ExportGenerationError())


@router.post("/comparisons/export.csv", summary="Export a comparison as CSV ZIP")
def export_comparison_csv(request: ComparisonRequest, session: SessionDependency):
    return _comparison_export(request, session, False)


@router.post("/comparisons/export.xlsx", summary="Export a comparison as Excel")
def export_comparison_excel(request: ComparisonRequest, session: SessionDependency):
    return _comparison_export(request, session, True)
