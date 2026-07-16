"use client";

import { memo } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface ResourceActionsProps {
  isRefreshing: boolean;
  onRefresh: () => void;
  children?: React.ReactNode;
}

export const ResourceActions = memo(function ResourceActions({
  isRefreshing,
  onRefresh,
  children,
}: ResourceActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {children}
      <Button
        type="button"
        variant="outline"
        onClick={onRefresh}
        disabled={isRefreshing}
        aria-label="Refresh resource data"
      >
        <RefreshCw
          className={isRefreshing ? "animate-spin" : undefined}
          aria-hidden="true"
        />
        {isRefreshing ? "Refreshing…" : "Refresh"}
      </Button>
    </div>
  );
});
