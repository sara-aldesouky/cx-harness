"use client";

import { useState } from "react";
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
  serverFilters?: ServerFilterDefinition[];
  serverFilterValues?: Record<string, string>;
  onServerFilterChange?: (key: string, value: string) => void;
}

export interface ServerFilterOption {
  label: string;
  value: string;
}

export interface ServerFilterDefinition {
  key: string;
  label: string;
  placeholder?: string;
  options?: ServerFilterOption[];
}

interface ServerTextFilterProps {
  filter: ServerFilterDefinition;
  value: string;
  onChange: (key: string, value: string) => void;
}

function ServerTextFilter({ filter, value, onChange }: ServerTextFilterProps) {
  const [draftValue, setDraftValue] = useState(value);

  const applyFilter = () => {
    if (draftValue !== value) {
      onChange(filter.key, draftValue.trim());
    }
  };

  return (
    <Input
      value={draftValue}
      onChange={(event) => setDraftValue(event.target.value)}
      onBlur={applyFilter}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          applyFilter();
        }
      }}
      placeholder={filter.placeholder ?? `Filter ${filter.label}…`}
      className="w-full sm:max-w-xs"
      aria-label={`Filter by ${filter.label}`}
    />
  );
}

export function DataTableFilters<TData>({
  table,
  selectedColumn,
  onSelectedColumnChange,
  serverFilters = [],
  serverFilterValues = {},
  onServerFilterChange,
}: DataTableFiltersProps<TData>) {
  const filterableColumns = table
    .getAllLeafColumns()
    .filter((column) => column.getCanFilter() && column.id !== "select");
  const activeColumn = table.getColumn(selectedColumn);
  const filterValue = String(activeColumn?.getFilterValue() ?? "");
  const hasServerFilters = Object.values(serverFilterValues).some(Boolean);
  const hasFilters =
    table.getState().columnFilters.length > 0 || hasServerFilters;

  if (filterableColumns.length === 0 && serverFilters.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2">
      {serverFilters.length > 0 ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {serverFilters.map((filter) =>
            filter.options ? (
              <Select
                key={filter.key}
                value={serverFilterValues[filter.key] || "__all__"}
                onValueChange={(value) =>
                  onServerFilterChange?.(
                    filter.key,
                    value === "__all__" || value === null ? "" : value,
                  )
                }
              >
                <SelectTrigger
                  className="w-full sm:w-48"
                  aria-label={`Filter by ${filter.label}`}
                >
                  <SelectValue>
                    {serverFilterValues[filter.key]
                      ? filter.options.find(
                          (option) =>
                            option.value === serverFilterValues[filter.key],
                        )?.label
                      : `All ${filter.label}`}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All {filter.label}</SelectItem>
                  {filter.options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <ServerTextFilter
                key={`${filter.key}:${serverFilterValues[filter.key] ?? ""}`}
                filter={filter}
                value={serverFilterValues[filter.key] ?? ""}
                onChange={(key, value) => onServerFilterChange?.(key, value)}
              />
            ),
          )}
        </div>
      ) : null}
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
            onClick={() => {
              table.resetColumnFilters();
              Object.keys(serverFilterValues).forEach((key) =>
                onServerFilterChange?.(key, ""),
              );
            }}
          >
            <X className="size-4" aria-hidden="true" />
            Clear filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}
