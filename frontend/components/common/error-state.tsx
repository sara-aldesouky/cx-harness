import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({
  title = "Something went wrong",
  message = "The requested content could not be loaded.",
  onRetry,
}: ErrorStateProps) {
  return (
    <div
      className="border-destructive/30 bg-destructive/5 flex min-h-48 flex-col items-center justify-center rounded-xl border p-8 text-center"
      role="alert"
    >
      <CircleAlert
        className="text-destructive mb-4 size-8"
        aria-hidden="true"
      />
      <h2 className="font-medium">{title}</h2>
      <p className="text-muted-foreground mt-1 max-w-md text-sm">{message}</p>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          className="mt-4"
          onClick={onRetry}
        >
          Try again
        </Button>
      ) : null}
    </div>
  );
}
