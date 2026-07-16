import { Inbox } from "lucide-react";

export interface EmptyStateProps {
  title?: string;
  description?: string;
}

export function EmptyState({
  title = "No results",
  description = "There is no data to display yet.",
}: EmptyStateProps) {
  return (
    <div className="bg-card flex min-h-48 flex-col items-center justify-center rounded-xl border border-dashed p-8 text-center">
      <Inbox className="text-muted-foreground mb-4 size-8" aria-hidden="true" />
      <h2 className="font-medium">{title}</h2>
      <p className="text-muted-foreground mt-1 max-w-md text-sm">
        {description}
      </p>
    </div>
  );
}
