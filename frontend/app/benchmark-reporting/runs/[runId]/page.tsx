import { RunDetailClient } from "@/components/benchmark-reporting/run-detail-client";
import { PageContainer } from "@/components/common/page-container";

export default async function BenchmarkRunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return (
    <PageContainer>
      <RunDetailClient runId={runId} />
    </PageContainer>
  );
}
