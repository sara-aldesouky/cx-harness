import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface StatCardProps {
  title: string;
  value: number;
  description: string;
  icon: LucideIcon;
}

export function StatCard({
  title,
  value,
  description,
  icon: Icon,
}: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="text-muted-foreground size-4" aria-hidden="true" />
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tracking-tight">
          {value.toLocaleString()}
        </p>
        <p className="text-muted-foreground mt-1 text-xs">{description}</p>
      </CardContent>
    </Card>
  );
}
