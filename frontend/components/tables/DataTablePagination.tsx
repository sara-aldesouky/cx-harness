"use client";

import type { Table } from "@tanstack/react-table";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface DataTablePaginationProps<TData> {
  table: Table<TData>;
  totalRows: number;
}

export function DataTablePagination<TData>({
  table,
  totalRows,
}: DataTablePaginationProps<TData>) {
  const { pageIndex, pageSize } = table.getState().pagination;
  const start = totalRows === 0 ? 0 : pageIndex * pageSize + 1;
  const end = Math.min((pageIndex + 1) * pageSize, totalRows);
  const selectedRows = table.getSelectedRowModel().rows.length;

  return (
    <div className="text-muted-foreground flex flex-col gap-3 px-1 py-1 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div aria-live="polite">
        Showing {start}–{end} of {totalRows} records
        {selectedRows > 0 ? ` · ${selectedRows} selected on this page` : ""}
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor="data-table-page-size">Rows per page</label>
        <Select
          value={String(pageSize)}
          onValueChange={(value) => table.setPageSize(Number(value))}
        >
          <SelectTrigger id="data-table-page-size" className="w-20">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[10, 20, 50, 100].map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => table.previousPage()}
          disabled={!table.getCanPreviousPage()}
          aria-label="Go to previous page"
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
        </Button>
        <span className="text-foreground min-w-20 text-center">
          Page {pageIndex + 1} of {Math.max(table.getPageCount(), 1)}
        </span>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => table.nextPage()}
          disabled={!table.getCanNextPage()}
          aria-label="Go to next page"
        >
          <ChevronRight className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
