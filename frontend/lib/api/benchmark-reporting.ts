import { apiClient } from "@/lib/api/client";
import type {
  BenchmarkRunPage,
  BenchmarkRunReport,
  ModelComparisonReport,
} from "@/types/benchmark-reporting";

export async function listBenchmarkRuns(
  params: Record<string, string | number>,
) {
  return (
    await apiClient.get<BenchmarkRunPage>("/benchmark-reporting/runs", {
      params,
    })
  ).data;
}

export async function getBenchmarkRun(runId: string) {
  return (
    await apiClient.get<BenchmarkRunReport>(
      `/benchmark-reporting/runs/${runId}`,
    )
  ).data;
}

export async function compareBenchmarkRuns(runIds: string[]) {
  return (
    await apiClient.post<ModelComparisonReport>(
      "/benchmark-reporting/comparisons",
      {
        run_ids: runIds,
      },
    )
  ).data;
}

export async function downloadExport(
  url: string,
  body?: { run_ids: string[] },
) {
  // Report generation can legitimately take longer than interactive API reads,
  // especially when a workbook contains evidence for a full benchmark campaign.
  // Keep this timeout local to exports so ordinary dashboard requests retain the
  // stricter client timeout.
  const exportRequest = { responseType: "blob" as const, timeout: 180_000 };
  const response = body
    ? await apiClient.post<Blob>(url, body, exportRequest)
    : await apiClient.get<Blob>(url, exportRequest);
  const disposition = response.headers["content-disposition"] as
    string | undefined;
  const filename =
    disposition?.match(/filename="([^"]+)"/)?.[1] ?? "benchmark-export";
  const objectUrl = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
}
