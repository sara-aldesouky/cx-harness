"""Ingest or remove the sanitized Stage 15.3 demonstration in local PostgreSQL."""

import argparse
from datetime import datetime, timezone

from sqlalchemy.engine import make_url

from app.benchmark_analytics.contracts import BenchmarkSuiteDefinition
from app.benchmark_analytics.repositories import BenchmarkRunRepository, BenchmarkSuiteRepository
from app.benchmark_ingestion.backfill import build_stage_15_3_backfill
from app.benchmark_ingestion.service import BenchmarkIngestionService
from app.database.session import get_session_factory


def _require_local(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or (parsed.host or "").lower() not in {"localhost","127.0.0.1","::1"}:
        raise RuntimeError("Stage 15.3 analytics backfill is restricted to local PostgreSQL")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--cleanup",action="store_true"); args=parser.parse_args()
    factory=get_session_factory(); _require_local(str(factory.kw["bind"].url))
    request=build_stage_15_3_backfill()
    with factory() as session:
        suites=BenchmarkSuiteRepository(session); runs=BenchmarkRunRepository(session)
        existing_run=runs.get_by_run_key(request.identity.run_key)
        if args.cleanup:
            if existing_run: runs.delete(existing_run.id)
            suite=suites.get_by_key_version(request.identity.suite_key,request.identity.suite_version)
            if suite and not runs.list_by_suite(suite.id): suites.delete(suite.id)
            session.commit(); print("Sanitized Stage 15.3 analytics demonstration removed."); return 0
        suite=suites.get_by_key_version(request.identity.suite_key,request.identity.suite_version)
        if suite is None:
            now=datetime.now(timezone.utc)
            suites.create(BenchmarkSuiteDefinition(
                suite_key=request.identity.suite_key,name="Stage 15.3 Validation Demonstration",
                description="Sanitized deterministic local ingestion demonstration.",version="1",
                test_case_count=len(request.conversations),content_hash="sha256:stage-15-3-sanitized-v1",
                created_at=now,updated_at=now,
            ))
        service=BenchmarkIngestionService(session)
        result=service.ingest_request(request)
        run=runs.get_by_id(result.benchmark_run_id)
        if run.status.value == "running": service.finalize_run(run.id)
        session.commit()
        print(f"Sanitized Stage 15.3 analytics demonstration ready: {request.identity.run_key}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
