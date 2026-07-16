"use client";

import { messageColumns } from "@/app/messages/columns";
import { ResourcePage } from "@/components/resources";
import type { ServerFilterDefinition } from "@/components/tables/DataTableFilters";
import type { MessageSummary } from "@/types";

const messageFilters: ServerFilterDefinition[] = [
  {
    key: "conversation_id",
    label: "conversation ID",
    placeholder: "Filter by conversation ID…",
  },
  {
    key: "role",
    label: "roles",
    options: [
      { label: "User", value: "user" },
      { label: "Assistant", value: "assistant" },
      { label: "System", value: "system" },
      { label: "Tool", value: "tool" },
    ],
  },
  {
    key: "language",
    label: "languages",
    options: [
      { label: "Egyptian Arabic", value: "egyptian_arabic" },
      { label: "Arabic", value: "arabic" },
      { label: "Franco Arabic", value: "franco_arabic" },
      { label: "English", value: "english" },
      { label: "Mixed", value: "mixed" },
      { label: "Unknown", value: "unknown" },
    ],
  },
];

export default function MessagesPage() {
  return (
    <ResourcePage<MessageSummary>
      title="Messages"
      endpoint="/messages"
      columns={messageColumns}
      description="View and search customer-support messages"
      filters={messageFilters}
    />
  );
}
