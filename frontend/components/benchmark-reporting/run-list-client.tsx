"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Download, GitCompareArrows, Search } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  downloadExport,
  listBenchmarkRuns,
} from "@/lib/api/benchmark-reporting";
import type { BenchmarkRunListItem } from "@/types/benchmark-reporting";
import { formatValue } from "./reporting-ui";

export function RunListClient() {
  const [runs, setRuns] = useState<BenchmarkRunListItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const load = () => {
    setLoading(true);
    setError(false);
    listBenchmarkRuns({ limit: 100, ...(status ? { status } : {}) })
      .then((data) => setRuns(data.items))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    listBenchmarkRuns({ limit: 100, ...(status ? { status } : {}) })
      .then((data) => setRuns(data.items))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [status]);
  const visible = runs.filter((run) =>
    `${run.model_name} ${run.provider_name} ${run.suite_key}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  if (loading) return <LoadingState label="Loading benchmark runs" />;
  if (error)
    return (
      <ErrorState
        title="Benchmark reports are unavailable"
        message="The benchmark API is currently unavailable."
        onRetry={load}
      />
    );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-3">
        <label className="relative flex-1">
          <span className="sr-only">Search benchmark runs</span>
          <Search className="absolute top-2.5 left-3 h-4 w-4" />
          <Input
            className="pl-9"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search models, providers, or suites"
          />
        </label>
        <select
          aria-label="Filter by status"
          className="bg-background rounded-md border px-3"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">All statuses</option>
          <option value="completed">Completed</option>
          <option value="partially_completed">Incomplete</option>
          <option value="failed">Failed</option>
        </select>
        {selected.length >= 2 && (
          <Link
            className="bg-primary text-primary-foreground inline-flex items-center gap-2 rounded-md px-3 text-sm font-medium"
            href={`/benchmark-reporting/compare?runs=${selected.join(",")}`}
          >
            <GitCompareArrows className="h-4 w-4" />
            Compare {selected.length}
          </Link>
        )}
      </div>
      {!visible.length ? (
        <EmptyState
          title="No benchmark runs"
          description="No benchmark campaigns have been recorded yet, or the current filters match no runs."
        />
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                {[
                  "Compare",
                  "Model",
                  "Provider",
                  "Suite",
                  "Status",
                  "Cases",
                  "Pass rate",
                  "Score",
                  "Coverage",
                  "Created",
                  "Actions",
                ].map((x) => (
                  <th className="p-3 text-left" key={x}>
                    {x}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((run) => (
                <tr className="border-t" key={run.run_id}>
                  <td className="p-3">
                    <input
                      aria-label={`Select ${run.model_name}`}
                      type="checkbox"
                      checked={selected.includes(run.run_id)}
                      onChange={(event) =>
                        setSelected(
                          event.target.checked
                            ? [...selected, run.run_id]
                            : selected.filter((id) => id !== run.run_id),
                        )
                      }
                    />
                  </td>
                  <td className="p-3 font-medium">{run.model_name}</td>
                  <td className="p-3">{run.provider_name}</td>
                  <td className="p-3">
                    {run.suite_key} v{run.suite_version}
                  </td>
                  <td className="p-3">
                    <Badge
                      variant={
                        run.status === "completed" ? "default" : "secondary"
                      }
                    >
                      {run.status.replaceAll("_", " ")}
                    </Badge>
                  </td>
                  <td className="p-3">
                    {run.completed_test_count}/{run.expected_test_count}
                  </td>
                  <td className="p-3">
                    {formatValue(run.pass_rate, "percent")}
                  </td>
                  <td className="p-3">{formatValue(run.overall_score)}</td>
                  <td className="p-3">
                    {formatValue(run.score_coverage, "percent")}
                  </td>
                  <td className="p-3">
                    {new Date(run.created_at).toLocaleDateString()}
                  </td>
                  <td className="p-3">
                    <div className="flex gap-2">
                      <Link
                        className="rounded-md border px-2 py-1 text-xs font-medium"
                        href={`/benchmark-reporting/runs/${run.run_id}`}
                      >
                        Open
                      </Link>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Export ${run.model_name} to Excel`}
                        onClick={() =>
                          downloadExport(
                            `/benchmark-reporting/runs/${run.run_id}/export.xlsx`,
                          )
                        }
                      >
                        <Download />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
