import { Cpu } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ModelRunSummary } from "@/types";

export function RecentModelRuns({ runs }: { runs: ModelRunSummary[] }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Cpu className="text-muted-foreground size-4" aria-hidden="true" />
          <CardTitle>Recent model runs</CardTitle>
        </div>
        <CardDescription>Latest model execution telemetry</CardDescription>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <EmptyState
            title="No model runs"
            description="Model executions will appear here."
          />
        ) : (
          <ul className="divide-y" aria-label="Recent model runs">
            {runs.map((run) => (
              <li
                key={run.id}
                className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {run.model_name}
                  </p>
                  <p className="text-muted-foreground text-xs capitalize">
                    {run.provider} ·{" "}
                    {run.latency_ms === null
                      ? "Latency unavailable"
                      : `${run.latency_ms.toLocaleString()} ms`}
                  </p>
                </div>
                <Badge variant={run.success ? "secondary" : "destructive"}>
                  {run.status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
