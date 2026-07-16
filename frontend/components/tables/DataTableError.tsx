import { CircleAlert, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface DataTableErrorProps {
  message?: string;
  onRetry: () => void;
}

export function DataTableError({
  message = "The records could not be loaded. Please try again.",
  onRetry,
}: DataTableErrorProps) {
  return (
    <div
      className="border-destructive/30 bg-destructive/5 flex min-h-56 flex-col items-center justify-center gap-3 rounded-lg border p-8 text-center"
      role="alert"
    >
      <CircleAlert className="text-destructive size-8" aria-hidden="true" />
      <div>
        <p className="font-medium">Unable to load records</p>
        <p className="text-muted-foreground mt-1 text-sm">{message}</p>
      </div>
      <Button type="button" variant="outline" onClick={onRetry}>
        <RotateCcw className="size-4" aria-hidden="true" />
        Retry
      </Button>
    </div>
  );
}
