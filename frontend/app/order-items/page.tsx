"use client";

import { orderItemColumns } from "@/app/order-items/columns";
import { ResourcePage } from "@/components/resources";
import type { ServerFilterDefinition } from "@/components/tables/DataTableFilters";
import type { OrderItemSummary } from "@/types";

const orderItemFilters: ServerFilterDefinition[] = [
  {
    key: "order_id",
    label: "order ID",
    placeholder: "Filter by order ID…",
  },
  {
    key: "item_status",
    label: "item statuses",
    options: [
      { label: "Included", value: "included" },
      { label: "Missing", value: "missing" },
      { label: "Replaced", value: "replaced" },
      { label: "Refunded", value: "refunded" },
    ],
  },
];

export default function OrderItemsPage() {
  return (
    <ResourcePage<OrderItemSummary>
      title="Order Items"
      endpoint="/order-items"
      columns={orderItemColumns}
      description="View and search products included in customer orders"
      filters={orderItemFilters}
    />
  );
}
