"use client";

import { conversationColumns } from "@/app/conversations/columns";
import { ResourcePage } from "@/components/resources";
import type { ServerFilterDefinition } from "@/components/tables/DataTableFilters";
import type { ConversationSummary } from "@/types";

const conversationFilters: ServerFilterDefinition[] = [
  {
    key: "customer_id",
    label: "customer ID",
    placeholder: "Filter by customer ID…",
  },
  {
    key: "related_order_id",
    label: "related order ID",
    placeholder: "Filter by related order ID…",
  },
  {
    key: "status",
    label: "conversation statuses",
    options: [
      { label: "Open", value: "open" },
      { label: "Waiting for customer", value: "waiting_for_customer" },
      { label: "Waiting for agent", value: "waiting_for_agent" },
      { label: "Resolved", value: "resolved" },
      { label: "Escalated", value: "escalated" },
      { label: "Closed", value: "closed" },
    ],
  },
  {
    key: "channel",
    label: "channels",
    options: [
      { label: "Web", value: "web" },
      { label: "Mobile", value: "mobile" },
      { label: "WhatsApp", value: "whatsapp" },
      { label: "Internal test", value: "internal_test" },
    ],
  },
];

export default function ConversationsPage() {
  return (
    <ResourcePage<ConversationSummary>
      title="Conversations"
      endpoint="/conversations"
      columns={conversationColumns}
      description="View and search customer-support conversations"
      filters={conversationFilters}
    />
  );
}
