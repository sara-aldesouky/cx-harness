import { memo } from "react";

export interface ResourceHeaderProps {
  title: string;
  description?: string;
  lastUpdatedAt: number | null;
  actions: React.ReactNode;
}

const timestampFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export const ResourceHeader = memo(function ResourceHeader({
  title,
  description,
  lastUpdatedAt,
  actions,
}: ResourceHeaderProps) {
  return (
    <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        ) : null}
        <p className="text-muted-foreground mt-2 text-xs" aria-live="polite">
          {lastUpdatedAt
            ? `Last updated ${timestampFormatter.format(lastUpdatedAt)}`
            : "Waiting for the latest data"}
        </p>
      </div>
      {actions}
    </header>
  );
});
