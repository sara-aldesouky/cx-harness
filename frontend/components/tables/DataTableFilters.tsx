"use client";

import type { Table } from "@tanstack/react-table";
import { ListFilter, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface DataTableFiltersProps<TData> {
  table: Table<TData>;
  selectedColumn: string;
  onSelectedColumnChange: (columnId: string) => void;
}

export function DataTableFilters<TData>({
  table,
  selectedColumn,
  onSelectedColumnChange,
}: DataTableFiltersProps<TData>) {
  const filterableColumns = table
    .getAllLeafColumns()
    .filter((column) => column.getCanFilter() && column.id !== "select");
  const activeColumn = table.getColumn(selectedColumn);
  const filterValue = String(activeColumn?.getFilterValue() ?? "");
  const hasFilters = table.getState().columnFilters.length > 0;

  if (filterableColumns.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-1 flex-col gap-2 sm:flex-row">
      <Select
        value={selectedColumn}
        onValueChange={(value) => {
          if (value !== null) {
            onSelectedColumnChange(value);
          }
        }}
      >
        <SelectTrigger
          className="w-full sm:w-44"
          aria-label="Select column to filter"
        >
          <ListFilter className="size-4" aria-hidden="true" />
          <SelectValue placeholder="Filter column" />
        </SelectTrigger>
        <SelectContent>
          {filterableColumns.map((column) => (
            <SelectItem key={column.id} value={column.id}>
              {column.id.replaceAll("_", " ")}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        value={filterValue}
        onChange={(event) => activeColumn?.setFilterValue(event.target.value)}
        placeholder={`Filter ${selectedColumn.replaceAll("_", " ")}…`}
        className="w-full sm:max-w-xs"
        aria-label={`Filter by ${selectedColumn.replaceAll("_", " ")}`}
      />
      {hasFilters ? (
        <Button
          type="button"
          variant="ghost"
          onClick={() => table.resetColumnFilters()}
        >
          <X className="size-4" aria-hidden="true" />
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
