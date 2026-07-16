"use client";

import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import type { ConversationSummary } from "@/types";

const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

const statusVariants = {
  open: "secondary",
  waiting_for_customer: "outline",
  waiting_for_agent: "outline",
  resolved: "secondary",
  escalated: "destructive",
  closed: "outline",
} as const;

const compactUuid = (value: string) =>
  `${value.slice(0, 8)}…${value.slice(-4)}`;

const formatLabel = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

function CompactIdentifier({ value }: { value: string }) {
  return (
    <span className="font-mono text-xs" title={value}>
      {compactUuid(value)}
    </span>
  );
}

export const conversationColumns: ColumnDef<ConversationSummary, unknown>[] = [
  {
    accessorKey: "id",
    header: "Conversation ID",
    cell: ({ getValue }) => <CompactIdentifier value={getValue<string>()} />,
  },
  {
    accessorKey: "customer_id",
    header: "Customer ID",
    cell: ({ getValue }) => <CompactIdentifier value={getValue<string>()} />,
  },
  {
    accessorKey: "related_order_id",
    header: "Related order ID",
    cell: ({ getValue }) => {
      const value = getValue<string | null>();
      return value ? <CompactIdentifier value={value} /> : "—";
    },
  },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ getValue }) => {
      const status = getValue<string>();
      return (
        <Badge
          variant={
            statusVariants[status as keyof typeof statusVariants] ?? "outline"
          }
        >
          {formatLabel(status)}
        </Badge>
      );
    },
  },
  {
    accessorKey: "channel",
    header: "Channel",
    cell: ({ getValue }) => (
      <Badge variant="outline">{formatLabel(getValue<string>())}</Badge>
    ),
  },
  {
    accessorKey: "active_model",
    header: "Active model",
    cell: ({ getValue }) => {
      const value = getValue<string | null>();
      return value ? formatLabel(value) : "Not selected";
    },
  },
  {
    accessorKey: "started_at",
    header: "Started at",
    cell: ({ getValue }) =>
      dateTimeFormatter.format(new Date(getValue<string>())),
  },
  {
    accessorKey: "ended_at",
    header: "Ended at",
    cell: ({ getValue }) => {
      const value = getValue<string | null>();
      return value ? dateTimeFormatter.format(new Date(value)) : "—";
    },
  },
  {
    accessorKey: "updated_at",
    header: "Last updated",
    cell: ({ getValue }) =>
      dateTimeFormatter.format(new Date(getValue<string>())),
  },
];
