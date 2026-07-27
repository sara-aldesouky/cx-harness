"""Read-only query boundary for benchmark reporting."""

from sqlalchemy.orm import Session
from app.benchmark_analytics.repositories import (
    BenchmarkConversationResultRepository,BenchmarkFailureRepository,
    BenchmarkMetricRepository,BenchmarkProviderTurnRepository,BenchmarkRunRepository,
    BenchmarkSuiteRepository,BenchmarkToolExecutionRepository,
)
from app.benchmark_reporting.contracts import RunAnalyticsSnapshot
from app.benchmark_reporting.errors import RunNotFoundError

class BenchmarkReportingRepository:
    def __init__(self,session:Session):
        self._runs=BenchmarkRunRepository(session); self._suites=BenchmarkSuiteRepository(session)
        self._conversations=BenchmarkConversationResultRepository(session)
        self._turns=BenchmarkProviderTurnRepository(session); self._tools=BenchmarkToolExecutionRepository(session)
        self._metrics=BenchmarkMetricRepository(session); self._failures=BenchmarkFailureRepository(session)

    def load_run(self,run_id):
        run=self._runs.get_by_id(run_id)
        if run is None: raise RunNotFoundError("benchmark run not found")
        suite=self._suites.get_by_id(run.benchmark_suite_id)
        if suite is None: raise RunNotFoundError("benchmark suite not found")
        conversations=self._conversations.list_by_run(run_id)
        turns=[]; tools=[]; metrics=[]; failures=[]
        for conversation in conversations:
            turns.extend(self._turns.list_in_order(conversation.id))
            tools.extend(self._tools.list_by_conversation(conversation.id))
            metrics.extend(self._metrics.list_by_conversation(conversation.id))
            failures.extend(self._failures.list_by_conversation(conversation.id))
        return RunAnalyticsSnapshot(suite=suite,run=run,conversations=conversations,
            provider_turns=tuple(turns),tool_executions=tuple(tools),metrics=tuple(metrics),failures=tuple(failures))
