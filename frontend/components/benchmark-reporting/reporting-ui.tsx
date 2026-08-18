"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Minus, TrendingUp } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OptionalNumber } from "@/types/benchmark-reporting";

export function formatValue(
  value: unknown,
  kind: "number" | "percent" | "latency" = "number",
) {
  if (value === null || value === undefined || value === "")
    return "Unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (kind === "percent") return `${(number * 100).toFixed(1)}%`;
  if (kind === "latency")
    return `${number.toLocaleString(undefined, { maximumFractionDigits: 1 })} ms`;
  return number.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

export function MetricCard({
  label,
  value,
  kind = "number",
}: {
  label: string;
  value: OptionalNumber | boolean;
  kind?: "number" | "percent" | "latency";
}) {
  return (
    <Card className="overflow-hidden border-slate-200 bg-white shadow-sm transition-shadow hover:shadow-md dark:border-slate-800 dark:bg-slate-950">
      <div className="h-1 bg-gradient-to-r from-sky-500 to-indigo-500" />
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-semibold tracking-[0.12em] text-slate-500 uppercase">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex items-end justify-between gap-3 pb-5">
        <span className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white">
          {typeof value === "boolean"
            ? value
              ? "Available"
              : "Unavailable"
            : formatValue(value, kind)}
        </span>
        <TrendingUp className="h-4 w-4 text-sky-500" />
      </CardContent>
    </Card>
  );
}

export function ReportSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="border-b border-slate-200 pb-3 dark:border-slate-800">
        <h2 className="text-xl font-bold tracking-tight">{title}</h2>
        {description && (
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        )}
      </div>
      {children}
    </section>
  );
}

function rawText(value: unknown) {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function EvidenceTable({
  rows,
  searchable = false,
}: {
  rows: Array<Record<string, unknown>>;
  searchable?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{
    column: string;
    direction: "asc" | "desc";
  } | null>(null);
  const visible = useMemo(() => {
    const filtered = !query
      ? rows
      : rows.filter((row) =>
          Object.values(row).some((value) =>
            rawText(value).toLowerCase().includes(query.toLowerCase()),
          ),
        );
    if (!sort) return filtered;
    return [...filtered].sort(
      (left, right) =>
        rawText(left[sort.column]).localeCompare(
          rawText(right[sort.column]),
          undefined,
          { numeric: true },
        ) * (sort.direction === "asc" ? 1 : -1),
    );
  }, [query, rows, sort]);
  if (!rows.length)
    return (
      <p className="text-muted-foreground rounded-md border p-5 text-sm">
        No measured evidence is available for this section.
      </p>
    );
  const columns = Object.keys(rows[0]);
  return (
    <div className="space-y-3">
      {searchable && (
        <input
          className="bg-background h-10 w-full max-w-sm rounded-lg border px-3 text-sm ring-sky-500 outline-none focus:ring-2"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter this evidence…"
        />
      )}
      <div className="max-h-[34rem] overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-slate-100/95 backdrop-blur dark:bg-slate-900/95">
            <tr>
              {columns.map((column) => (
                <th
                  className="px-4 py-3 text-left text-xs font-semibold tracking-wide whitespace-nowrap text-slate-600 uppercase dark:text-slate-300"
                  key={column}
                >
                  <button
                    className="inline-flex items-center gap-1 hover:text-sky-600"
                    onClick={() =>
                      setSort((current) =>
                        current?.column === column
                          ? {
                              column,
                              direction:
                                current.direction === "asc" ? "desc" : "asc",
                            }
                          : { column, direction: "asc" },
                      )
                    }
                  >
                    {column.replaceAll("_", " ")}
                    {sort?.column === column ? (
                      sort.direction === "asc" ? (
                        <ArrowUp className="h-3 w-3" />
                      ) : (
                        <ArrowDown className="h-3 w-3" />
                      )
                    ) : (
                      <Minus className="h-3 w-3 opacity-30" />
                    )}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr
                className="border-t border-slate-100 transition-colors hover:bg-sky-50/50 dark:border-slate-800 dark:hover:bg-sky-950/20"
                key={index}
              >
                {columns.map((column) => (
                  <td
                    className="max-w-80 px-4 py-3 align-top leading-6 break-words whitespace-normal"
                    key={column}
                    title={rawText(row[column])}
                  >
                    {typeof row[column] === "boolean"
                      ? row[column]
                        ? "✓"
                        : "✗"
                      : typeof row[column] === "object"
                        ? JSON.stringify(row[column])
                        : formatValue(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function HorizontalBarChart({
  rows,
  valueKind = "percent",
}: {
  rows: Array<{ label: string; value: OptionalNumber; color?: string }>;
  valueKind?: "percent" | "number" | "latency";
}) {
  const numeric = rows.map((row) => Number(row.value) || 0);
  const max = Math.max(...numeric, valueKind === "percent" ? 1 : 0.0001);
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      {rows.map((row, index) => (
        <div className="space-y-1.5" key={row.label}>
          <div className="flex justify-between gap-4 text-sm">
            <span className="font-medium">{row.label}</span>
            <span className="text-muted-foreground tabular-nums">
              {formatValue(row.value, valueKind)}
            </span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.max(2, (numeric[index] / max) * 100)}%`,
                backgroundColor: row.color ?? "#0ea5e9",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DonutChart({
  passed,
  failed,
}: {
  passed: number;
  failed: number;
}) {
  const total = passed + failed;
  const pass = total ? (passed / total) * 100 : 0;
  return (
    <div className="flex items-center gap-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div
        className="grid h-28 w-28 shrink-0 place-items-center rounded-full"
        style={{
          background: `conic-gradient(#10b981 0 ${pass}%, #f43f5e ${pass}% 100%)`,
        }}
      >
        <div className="grid h-20 w-20 place-items-center rounded-full bg-white text-center dark:bg-slate-950">
          <span className="text-xl font-bold">
            {formatValue(total ? passed / total : null, "percent")}
          </span>
        </div>
      </div>
      <div className="space-y-3">
        <p className="font-semibold">Pass vs fail</p>
        <p className="text-sm">
          <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" />
          Passed <strong>{passed}</strong>
        </p>
        <p className="text-sm">
          <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full bg-rose-500" />
          Failed <strong>{failed}</strong>
        </p>
      </div>
    </div>
  );
}
