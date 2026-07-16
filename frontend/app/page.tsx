import { PageContainer } from "@/components/common/page-container";
import { SectionHeader } from "@/components/common/section-header";

export default function Home() {
  return (
    <PageContainer>
      <SectionHeader
        title="Frontend foundation ready"
        description="Dashboard pages and backend queries will be added in later milestones."
      />
      <div className="bg-card text-muted-foreground rounded-xl border border-dashed p-8 text-sm">
        The application shell, theme support, API client, and query provider are
        configured.
      </div>
    </PageContainer>
  );
}
