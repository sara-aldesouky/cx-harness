import { memo } from "react";

export interface ResourceToolbarProps {
  children: React.ReactNode;
}

export const ResourceToolbar = memo(function ResourceToolbar({
  children,
}: ResourceToolbarProps) {
  return <div className="min-w-0">{children}</div>;
});
