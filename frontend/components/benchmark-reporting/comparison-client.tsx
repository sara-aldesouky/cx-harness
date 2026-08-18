"use client";

import { useEffect, useState } from "react";
import { Award, Download, Sparkles } from "lucide-react";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  compareBenchmarkRuns,
  downloadExport,
} from "@/lib/api/benchmark-reporting";
import type { ModelComparisonReport } from "@/types/benchmark-reporting";
import {
  EvidenceTable,
  HorizontalBarChart,
  MetricCard,
  ReportSection,
} from "./reporting-ui";

const MODEL_COLORS = [
  "#0ea5e9",
  "#8b5cf6",
  "#f59e0b",
  "#10b981",
  "#f43f5e",
  "#6366f1",
];

export function ComparisonClient({ runIds }: { runIds: string[] }) {
  const [report, setReport] = useState<ModelComparisonReport | null>(null);
  const [error, setError] = useState("");
  const runKey = runIds.join(",");
  const load = () => {
    setError("");
    if (runIds.length < 2) {
      setError("Select at least two unique benchmark runs.");
      return;
    }
    compareBenchmarkRuns(runIds)
      .then(setReport)
      .catch(
        (reason: {
          response?: { data?: { message?: string; details?: string[] } };
        }) =>
          setError(
            reason.response?.data?.details?.join(" ") ||
              reason.response?.data?.message ||
              "The selected runs are incompatible or unavailable.",
          ),
      );
  };
  useEffect(() => {
    const ids = runKey.split(",").filter(Boolean);
    if (ids.length >= 2)
      compareBenchmarkRuns(ids)
        .then(setReport)
        .catch(
          (reason: {
            response?: { data?: { message?: string; details?: string[] } };
          }) =>
            setError(
              reason.response?.data?.details?.join(" ") ||
                reason.response?.data?.message ||
                "The selected runs are incompatible or unavailable.",
            ),
        );
  }, [runKey]);
  if (runIds.length < 2)
    return (
      <ErrorState
        title="Comparison unavailable"
        message="Select at least two unique benchmark runs."
      />
    );
  if (error)
    return (
      <ErrorState
        title="Comparison unavailable"
        message={error}
        onRetry={runIds.length >= 2 ? load : undefined}
      />
    );
  if (!report) return <LoadingState label="Comparing benchmark runs" />;
  const overallWinner = report.winners.find(
    (winner) => winner.dimension === "overall_score" && winner.available,
  );
  const winningModel = report.runs.find(
    (run) => run.run.run_key === overallWinner?.winning_run_key,
  )?.run.model_name;
  return (
    <div className="space-y-10">
      <div className="rounded-2xl bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 p-7 text-white shadow-xl">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-[0.2em] text-sky-300 uppercase">
              {report.suite_key} · v{report.suite_version}
            </p>
            <h1 className="mt-2 text-4xl font-bold tracking-tight">
              Model comparison
            </h1>
            <p className="mt-2 text-slate-300">
              {report.runs.length} compatible runs · policy{" "}
              {report.scoring_policy_key} v{report.scoring_policy_version}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              className="bg-white text-slate-950 hover:bg-slate-100"
              variant="outline"
              onClick={() =>
                downloadExport("/benchmark-reporting/comparisons/export.csv", {
                  run_ids: runIds,
                })
              }
            >
              <Download />
              CSV ZIP
            </Button>
            <Button
              className="bg-sky-500 hover:bg-sky-400"
              onClick={() =>
                downloadExport("/benchmark-reporting/comparisons/export.xlsx", {
                  run_ids: runIds,
                })
              }
            >
              <Download />
              Excel
            </Button>
          </div>
        </div>
        {winningModel && (
          <div className="mt-6 flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-4">
            <Award className="h-6 w-6 text-amber-300" />
            <div>
              <p className="text-xs font-semibold tracking-wide text-amber-200 uppercase">
                Overall winner
              </p>
              <p className="text-xl font-bold">{winningModel}</p>
            </div>
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {report.runs.map((run, index) => (
          <Badge
            className="border-0 px-3 py-1.5 text-white"
            style={{
              backgroundColor: MODEL_COLORS[index % MODEL_COLORS.length],
            }}
            key={run.run.id}
          >
            {run.run.model_name} · {run.run.provider_name}
          </Badge>
        ))}
      </div>
      {!report.cost_ranking_available && (
        <div className="rounded-md border border-amber-400/50 bg-amber-50 p-4 text-sm text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
          Cost ranking is unavailable. Currency evidence is missing or
          incompatible; no conversion was attempted.
        </div>
      )}
      <ReportSection
        title="Executive summary"
        description="Consistent model colors are used throughout this comparison."
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {report.runs.map((run) => (
            <MetricCard
              key={run.run.id}
              label={`${run.run.model_name} overall score`}
              value={run.performance.overall_score}
            />
          ))}
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <HorizontalBarChart
            valueKind="number"
            rows={report.runs.map((run, index) => ({
              label: run.run.model_name,
              value: run.performance.overall_score,
              color: MODEL_COLORS[index % MODEL_COLORS.length],
            }))}
          />
          <HorizontalBarChart
            rows={report.runs.map((run, index) => ({
              label: `${run.run.model_name} pass rate`,
              value: run.completion.pass_rate,
              color: MODEL_COLORS[index % MODEL_COLORS.length],
            }))}
          />
        </div>
      </ReportSection>
      <ReportSection
        title="Performance by criterion"
        description="Unavailable evidence remains blank; zero is shown only when measured."
      >
        <EvidenceTable
          searchable
          rows={report.metric_rows as unknown as Array<Record<string, unknown>>}
        />
      </ReportSection>
      <ReportSection
        title="Winner analysis"
        description="Every recommendation is tied to the existing scoring engine’s explanation."
      >
        <div className="text-muted-foreground mb-4 flex items-center gap-2 text-sm">
          <Sparkles className="h-4 w-4 text-amber-500" />
          Best overall, fastest, lowest-cost, and quality leaders appear only
          when comparable evidence exists.
        </div>
        <EvidenceTable
          searchable
          rows={report.winners as unknown as Array<Record<string, unknown>>}
        />
      </ReportSection>
    </div>
  );
}
