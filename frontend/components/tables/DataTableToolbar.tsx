"use client";

import type { Table } from "@tanstack/react-table";
import { Columns3 } from "lucide-react";

import { DataTableFilters } from "@/components/tables/DataTableFilters";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";

interface DataTableToolbarProps<TData> {
  table: Table<TData>;
  globalFilter: string;
  onGlobalFilterChange: (value: string) => void;
  selectedColumn: string;
  onSelectedColumnChange: (columnId: string) => void;
}

export function DataTableToolbar<TData>({
  table,
  globalFilter,
  onGlobalFilterChange,
  selectedColumn,
  onSelectedColumnChange,
}: DataTableToolbarProps<TData>) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Input
          value={globalFilter}
          onChange={(event) => onGlobalFilterChange(event.target.value)}
          placeholder="Search loaded records…"
          className="w-full sm:max-w-sm"
          aria-label="Search loaded records"
        />
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button type="button" variant="outline" className="sm:ml-auto" />
            }
          >
            <Columns3 className="size-4" aria-hidden="true" />
            Columns
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {table
              .getAllLeafColumns()
              .filter((column) => column.getCanHide() && column.id !== "select")
              .map((column) => (
                <DropdownMenuCheckboxItem
                  key={column.id}
                  checked={column.getIsVisible()}
                  onCheckedChange={(value) =>
                    column.toggleVisibility(Boolean(value))
                  }
                >
                  {column.id.replaceAll("_", " ")}
                </DropdownMenuCheckboxItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <DataTableFilters
        table={table}
        selectedColumn={selectedColumn}
        onSelectedColumnChange={onSelectedColumnChange}
      />
    </div>
  );
}
