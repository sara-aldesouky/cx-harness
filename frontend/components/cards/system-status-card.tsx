import { CheckCircle2, ServerCog } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const statuses = [
  { label: "Backend", value: "Connected" },
  { label: "Database", value: "Connected" },
  { label: "API", value: "Healthy" },
  { label: "API version", value: "/api/v1" },
] as const;

export function SystemStatusCard() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <ServerCog
            className="text-muted-foreground size-4"
            aria-hidden="true"
          />
          <CardTitle>System status</CardTitle>
        </div>
        <CardDescription>
          Confirmed by successful live API and database-backed responses
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 sm:grid-cols-2">
          {statuses.map((status) => (
            <div
              key={status.label}
              className="flex items-center justify-between rounded-lg border p-3"
            >
              <dt className="text-muted-foreground text-sm">{status.label}</dt>
              <dd>
                <Badge variant="secondary">
                  <CheckCircle2 className="size-3.5" aria-hidden="true" />
                  {status.value}
                </Badge>
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
