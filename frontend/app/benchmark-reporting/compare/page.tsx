import { ComparisonClient } from "@/components/benchmark-reporting/comparison-client";
import { PageContainer } from "@/components/common/page-container";

export default async function BenchmarkComparisonPage({
  searchParams,
}: {
  searchParams: Promise<{ runs?: string }>;
}) {
  const { runs } = await searchParams;
  return (
    <PageContainer>
      <ComparisonClient runIds={(runs ?? "").split(",").filter(Boolean)} />
    </PageContainer>
  );
}
