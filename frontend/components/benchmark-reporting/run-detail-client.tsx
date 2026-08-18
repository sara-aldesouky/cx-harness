"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Gauge,
  Sparkles,
} from "lucide-react";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { Button } from "@/components/ui/button";
import { downloadExport, getBenchmarkRun } from "@/lib/api/benchmark-reporting";
import type { BenchmarkRunReport } from "@/types/benchmark-reporting";
import {
  DonutChart,
  EvidenceTable,
  HorizontalBarChart,
  MetricCard,
  ReportSection,
  formatValue,
} from "./reporting-ui";

export function RunDetailClient({ runId }: { runId: string }) {
  const [report, setReport] = useState<BenchmarkRunReport | null>(null);
  const [error, setError] = useState(false);
  const load = () => {
    setError(false);
    getBenchmarkRun(runId)
      .then(setReport)
      .catch(() => setError(true));
  };
  useEffect(() => {
    getBenchmarkRun(runId)
      .then(setReport)
      .catch(() => setError(true));
  }, [runId]);
  if (error)
    return (
      <ErrorState
        title="Run report unavailable"
        message="The report could not be generated from the available evidence."
        onRetry={load}
      />
    );
  if (!report) return <LoadingState label="Generating benchmark report" />;
  const passed = Number(report.completion.passed_cases ?? 0);
  const failed = Number(report.completion.failed_cases ?? 0);
  const toolRate = report.execution.tool_execution_success_rate;
  const criticalFailures =
    Number(report.reliability.conversations_with_security_failures ?? 0) +
    Number(report.reliability.conversations_with_infrastructure_failures ?? 0);
  const recommendation =
    Number(report.completion.pass_rate ?? 0) >= 0.9
      ? "Strong production candidate"
      : Number(report.completion.pass_rate ?? 0) >= 0.75
        ? "Promising — investigate failed cases"
        : "Not ready — material quality gaps";
  return (
    <div className="space-y-12">
      <div className="rounded-2xl bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 p-7 text-white shadow-xl">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="mb-2 text-xs font-semibold tracking-[0.2em] text-sky-300 uppercase">
              Executive benchmark report · {report.suite_key} v
              {report.suite_version}
            </p>
            <h1 className="text-4xl font-bold tracking-tight">
              {report.run.model_name}
            </h1>
            <p className="mt-2 text-slate-300">
              {report.run.provider_name} ·{" "}
              {report.run.status.replaceAll("_", " ")} · generated from measured
              evidence
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              className="bg-white text-slate-950 hover:bg-slate-100"
              variant="outline"
              onClick={() =>
                downloadExport(`/benchmark-reporting/runs/${runId}/export.csv`)
              }
            >
              <Download />
              CSV ZIP
            </Button>
            <Button
              className="bg-sky-500 hover:bg-sky-400"
              onClick={() =>
                downloadExport(`/benchmark-reporting/runs/${runId}/export.xlsx`)
              }
            >
              <Download />
              Excel
            </Button>
          </div>
        </div>
        <div className="mt-7 flex items-start gap-3 rounded-xl border border-white/10 bg-white/5 p-4">
          <Sparkles className="mt-0.5 h-5 w-5 text-sky-300" />
          <div>
            <p className="text-xs font-semibold tracking-wide text-sky-300 uppercase">
              Executive recommendation
            </p>
            <p className="mt-1 text-lg font-semibold">{recommendation}</p>
          </div>
        </div>
      </div>
      <ReportSection
        title="Executive summary"
        description="Decision-grade quality, reliability, speed, and cost indicators."
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <MetricCard
            label="Total test cases"
            value={report.completion.stored_test_cases}
          />
          <MetricCard
            label="Pass rate"
            value={report.completion.pass_rate}
            kind="percent"
          />
          <MetricCard
            label="Overall score"
            value={report.performance.overall_score}
          />
          <MetricCard
            label="Hallucination rate"
            value={report.hallucination.hallucination_rate}
            kind="percent"
          />
          <MetricCard
            label="Average latency"
            value={report.latency.average_conversation_latency_ms}
            kind="latency"
          />
          <MetricCard
            label="Total cost"
            value={report.cost.total_estimated_cost as string | number | null}
          />
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <DonutChart passed={passed} failed={failed} />
          <HorizontalBarChart
            rows={[
              {
                label: "Overall score",
                value: report.performance.overall_score,
                color: "#6366f1",
              },
              {
                label: "Pass rate",
                value: report.completion.pass_rate,
                color: "#10b981",
              },
              { label: "Tool success", value: toolRate, color: "#0ea5e9" },
              {
                label: "Grounding",
                value: report.grounding.grounding_pass_rate,
                color: "#8b5cf6",
              },
              {
                label: "Hallucination-free",
                value:
                  report.hallucination.hallucination_rate == null
                    ? null
                    : 1 - Number(report.hallucination.hallucination_rate),
                color: "#f59e0b",
              },
            ]}
          />
        </div>
      </ReportSection>
      <ReportSection
        title="Risk and efficiency"
        description="Critical failures remain separate from ordinary model-quality misses."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border p-5">
            <AlertTriangle className="mb-3 h-5 w-5 text-rose-500" />
            <p className="text-muted-foreground text-sm">Critical failures</p>
            <p className="mt-1 text-2xl font-bold">{criticalFailures}</p>
          </div>
          <div className="rounded-xl border p-5">
            <Gauge className="mb-3 h-5 w-5 text-sky-500" />
            <p className="text-muted-foreground text-sm">P95 latency</p>
            <p className="mt-1 text-2xl font-bold">
              {formatValue(report.latency.p95_ms, "latency")}
            </p>
          </div>
          <div className="rounded-xl border p-5">
            <CheckCircle2 className="mb-3 h-5 w-5 text-emerald-500" />
            <p className="text-muted-foreground text-sm">Score coverage</p>
            <p className="mt-1 text-2xl font-bold">
              {formatValue(report.performance.score_coverage, "percent")}
            </p>
          </div>
        </div>
      </ReportSection>
      <ReportSection
        title="Model test evidence"
        description="Primary case-level working area. Prompts and complete responses are shown only when the reporting contract supplies them."
      >
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center dark:border-slate-700 dark:bg-slate-900/50">
          <p className="font-semibold">
            Case-level prompt and response evidence is not exposed by this
            report API.
          </p>
          <p className="text-muted-foreground mx-auto mt-2 max-w-2xl text-sm">
            Aggregate case outcomes are preserved below. No customer question,
            model response, expected answer, or raw metadata has been inferred
            or fabricated in the presentation layer.
          </p>
        </div>
        <EvidenceTable
          searchable
          rows={[
            {
              test_cases: report.completion.stored_test_cases,
              passed: report.completion.passed_cases,
              failed: report.completion.failed_cases,
              completion_rate: report.completion.completion_rate,
              hallucination_rate: report.hallucination.hallucination_rate,
              grounding_pass_rate: report.grounding.grounding_pass_rate,
              average_latency_ms:
                report.latency.average_conversation_latency_ms,
              total_tokens: report.tokens.total_tokens,
              cost: report.cost.total_estimated_cost,
            },
          ]}
        />
      </ReportSection>
      <ReportSection title="Performance by criterion">
        <EvidenceTable searchable rows={report.quality_metrics} />
      </ReportSection>
      <ReportSection
        title="Language performance"
        description="Only languages represented by stored evidence appear."
      >
        <EvidenceTable
          rows={report.languages as unknown as Array<Record<string, unknown>>}
        />
      </ReportSection>
      <ReportSection title="Category, complexity, and pressure">
        <div className="grid gap-6 xl:grid-cols-3">
          <EvidenceTable
            rows={
              report.categories as unknown as Array<Record<string, unknown>>
            }
          />
          <EvidenceTable
            rows={
              report.complexity as unknown as Array<Record<string, unknown>>
            }
          />
          <EvidenceTable
            rows={report.pressure as unknown as Array<Record<string, unknown>>}
          />
        </div>
      </ReportSection>
      <ReportSection title="Tool analysis">
        <EvidenceTable
          searchable
          rows={report.tools as unknown as Array<Record<string, unknown>>}
        />
      </ReportSection>
      <ReportSection title="Failure analysis">
        <div className="grid gap-6 xl:grid-cols-2">
          <EvidenceTable rows={report.failure_categories} />
          <EvidenceTable rows={report.failure_responsibilities} />
        </div>
      </ReportSection>
      <ReportSection title="Intent analysis">
        <EvidenceTable rows={[report.intent]} />
      </ReportSection>
      <ReportSection title="Efficiency">
        <div className="grid gap-6 xl:grid-cols-3">
          <EvidenceTable rows={[report.tokens]} />
          <EvidenceTable rows={[report.latency]} />
          <EvidenceTable rows={[report.cost]} />
        </div>
      </ReportSection>
      <ReportSection
        title="Scoring"
        description={`Available: ${report.performance.available_dimensions.join(", ") || "none"}. Missing: ${report.performance.missing_dimensions.join(", ") || "none"}.`}
      >
        <EvidenceTable rows={report.performance.weighted_components} />
      </ReportSection>
    </div>
  );
}
