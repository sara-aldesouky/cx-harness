import { Skeleton } from "@/components/ui/skeleton";
import { TableBody, TableCell, TableRow } from "@/components/ui/table";

interface DataTableSkeletonProps {
  columnCount: number;
  rowCount?: number;
}

export function DataTableSkeleton({
  columnCount,
  rowCount = 8,
}: DataTableSkeletonProps) {
  return (
    <TableBody aria-label="Loading table data">
      {Array.from({ length: rowCount }, (_, rowIndex) => (
        <TableRow key={rowIndex}>
          {Array.from({ length: columnCount }, (_, columnIndex) => (
            <TableCell key={columnIndex}>
              <Skeleton className="h-5 w-full min-w-20" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </TableBody>
  );
}
