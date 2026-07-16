import { DataTableSkeleton } from "@/components/tables/DataTableSkeleton";

export function DataTableLoading({ columnCount }: { columnCount: number }) {
  return <DataTableSkeleton columnCount={columnCount} />;
}
