"use client";

import { memo, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  type ColumnDef,
  type ColumnFiltersState,
  type PaginationState,
  type RowData,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { DataTableEmpty } from "@/components/tables/DataTableEmpty";
import { DataTableError } from "@/components/tables/DataTableError";
import { DataTableLoading } from "@/components/tables/DataTableLoading";
import { DataTablePagination } from "@/components/tables/DataTablePagination";
import { DataTableToolbar } from "@/components/tables/DataTableToolbar";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import type { PaginatedResponse } from "@/types";

export interface DataTableProps<TData extends RowData> {
  endpoint: string;
  columns: ColumnDef<TData, unknown>[];
  title: string;
  initialPageSize?: number;
  getRowId?: (row: TData) => string;
}

async function fetchPage<TData>(
  endpoint: string,
  pagination: PaginationState,
): Promise<PaginatedResponse<TData>> {
  const response = await apiClient.get<PaginatedResponse<TData>>(endpoint, {
    params: {
      limit: pagination.pageSize,
      offset: pagination.pageIndex * pagination.pageSize,
    },
  });
  return response.data;
}

function DataTableComponent<TData extends RowData>({
  endpoint,
  columns,
  title,
  initialPageSize = 20,
  getRowId,
}: DataTableProps<TData>) {
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: initialPageSize,
  });
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const queryKey = useMemo(
    () => ["data-table", endpoint, pagination.pageIndex, pagination.pageSize],
    [endpoint, pagination.pageIndex, pagination.pageSize],
  );
  const query = useQuery({
    queryKey,
    queryFn: () => fetchPage<TData>(endpoint, pagination),
    placeholderData: keepPreviousData,
  });

  const selectionColumn = useMemo<ColumnDef<TData, unknown>>(
    () => ({
      id: "select",
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          data-indeterminate={table.getIsSomePageRowsSelected() || undefined}
          onCheckedChange={(value) =>
            table.toggleAllPageRowsSelected(Boolean(value))
          }
          aria-label="Select all rows on this page"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
          aria-label="Select row"
        />
      ),
      enableSorting: false,
      enableHiding: false,
      enableColumnFilter: false,
    }),
    [],
  );
  const tableColumns = useMemo(
    () => [selectionColumn, ...columns],
    [columns, selectionColumn],
  );

  // TanStack Table intentionally returns non-memoizable functions.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: query.data?.items ?? [],
    columns: tableColumns,
    pageCount: Math.ceil((query.data?.total ?? 0) / pagination.pageSize),
    state: {
      pagination,
      sorting,
      columnFilters,
      globalFilter,
      columnVisibility,
      rowSelection,
    },
    getRowId,
    manualPagination: true,
    enableMultiSort: true,
    enableRowSelection: true,
    onPaginationChange: setPagination,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const firstFilterableColumn =
    table
      .getAllLeafColumns()
      .find((column) => column.id !== "select" && column.getCanFilter())?.id ??
    "";
  const [selectedColumn, setSelectedColumn] = useState(firstFilterableColumn);
  const visibleColumnCount = table.getVisibleLeafColumns().length;

  return (
    <section className="space-y-4" aria-labelledby="data-table-title">
      <div>
        <h1
          id="data-table-title"
          className="text-2xl font-semibold tracking-tight"
        >
          {title}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Browse, sort, filter, and select records.
        </p>
      </div>

      <DataTableToolbar
        table={table}
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        selectedColumn={selectedColumn || firstFilterableColumn}
        onSelectedColumnChange={setSelectedColumn}
      />

      {query.isError ? (
        <DataTableError onRetry={() => void query.refetch()} />
      ) : (
        <div className="bg-card overflow-hidden rounded-xl border">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      const sortDirection = header.column.getIsSorted();
                      return (
                        <TableHead
                          key={header.id}
                          className="whitespace-nowrap"
                        >
                          {header.isPlaceholder ? null : header.column.getCanSort() ? (
                            <button
                              type="button"
                              onClick={header.column.getToggleSortingHandler()}
                              className="hover:text-foreground focus-visible:ring-ring flex items-center gap-2 rounded-sm font-medium focus-visible:ring-2 focus-visible:outline-none"
                              aria-label={`Sort by ${header.column.id}`}
                            >
                              {flexRender(
                                header.column.columnDef.header,
                                header.getContext(),
                              )}
                              {sortDirection === "asc" ? (
                                <ArrowUp
                                  className="size-3.5"
                                  aria-hidden="true"
                                />
                              ) : sortDirection === "desc" ? (
                                <ArrowDown
                                  className="size-3.5"
                                  aria-hidden="true"
                                />
                              ) : (
                                <ArrowUpDown
                                  className="text-muted-foreground size-3.5"
                                  aria-hidden="true"
                                />
                              )}
                            </button>
                          ) : (
                            flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )
                          )}
                        </TableHead>
                      );
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              {query.isPending ? (
                <DataTableLoading columnCount={visibleColumnCount} />
              ) : table.getRowModel().rows.length === 0 ? (
                <DataTableEmpty colSpan={visibleColumnCount} />
              ) : (
                <TableBody>
                  {table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() ? "selected" : undefined}
                      tabIndex={0}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="whitespace-nowrap">
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              )}
            </Table>
          </div>
        </div>
      )}

      <DataTablePagination table={table} totalRows={query.data?.total ?? 0} />
    </section>
  );
}

export const DataTable = memo(DataTableComponent) as typeof DataTableComponent;
