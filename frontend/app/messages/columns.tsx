"use client";

import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import type { MessageSummary } from "@/types";

const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

const roleVariants = {
  user: "secondary",
  assistant: "outline",
  system: "outline",
  tool: "secondary",
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

export const messageColumns: ColumnDef<MessageSummary, unknown>[] = [
  {
    accessorKey: "id",
    header: "Message ID",
    cell: ({ getValue }) => <CompactIdentifier value={getValue<string>()} />,
  },
  {
    accessorKey: "conversation_id",
    header: "Conversation ID",
    cell: ({ getValue }) => <CompactIdentifier value={getValue<string>()} />,
  },
  {
    accessorKey: "role",
    header: "Role",
    cell: ({ getValue }) => {
      const role = getValue<string>();
      return (
        <Badge
          variant={roleVariants[role as keyof typeof roleVariants] ?? "outline"}
        >
          {formatLabel(role)}
        </Badge>
      );
    },
  },
  {
    accessorKey: "content",
    header: "Content",
    cell: ({ getValue }) => {
      const content = getValue<string>();
      return (
        <span className="block max-w-96 truncate" title={content}>
          {content}
        </span>
      );
    },
  },
  {
    accessorKey: "language",
    header: "Language",
    cell: ({ getValue }) => {
      const language = getValue<string | null>();
      return language ? (
        <Badge variant="outline">{formatLabel(language)}</Badge>
      ) : (
        "—"
      );
    },
  },
  {
    accessorKey: "sequence_number",
    header: "Sequence number",
    cell: ({ getValue }) => (
      <span className="block text-right tabular-nums">
        {getValue<number>().toLocaleString("en")}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ getValue }) =>
      dateTimeFormatter.format(new Date(getValue<string>())),
  },
];
