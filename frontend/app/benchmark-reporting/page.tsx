import { RunListClient } from "@/components/benchmark-reporting/run-list-client";
import { PageContainer } from "@/components/common/page-container";

export default function BenchmarkRunsPage() {
  return (
    <PageContainer>
      <header className="rounded-2xl bg-gradient-to-br from-slate-950 to-indigo-950 p-7 text-white shadow-xl">
        <p className="text-xs font-semibold tracking-[0.2em] text-sky-300 uppercase">
          Model intelligence
        </p>
        <h1 className="mt-2 text-4xl font-bold tracking-tight">
          Benchmark reporting
        </h1>
        <p className="mt-2 max-w-2xl text-slate-300">
          Decision-ready model quality, reliability, speed, cost, and evaluation
          evidence for engineering leadership.
        </p>
      </header>
      <RunListClient />
    </PageContainer>
  );
}
