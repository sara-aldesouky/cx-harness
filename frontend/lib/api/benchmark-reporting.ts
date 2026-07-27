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
  const response = body
    ? await apiClient.post<Blob>(url, body, { responseType: "blob" })
    : await apiClient.get<Blob>(url, { responseType: "blob" });
  const disposition = response.headers["content-disposition"] as
    string | undefined;
  const filename =
    disposition?.match(/filename="([^"]+)"/)?.[1] ?? "benchmark-export";
  const objectUrl = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}
