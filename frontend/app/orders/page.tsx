"use client";

import { orderColumns } from "@/app/orders/columns";
import { ResourcePage } from "@/components/resources";
import type { ServerFilterDefinition } from "@/components/tables/DataTableFilters";
import type { OrderSummary } from "@/types";

const orderFilters: ServerFilterDefinition[] = [
  {
    key: "customer_id",
    label: "customer ID",
    placeholder: "Filter by customer ID…",
  },
  {
    key: "status",
    label: "order statuses",
    options: [
      { label: "Pending", value: "pending" },
      { label: "Confirmed", value: "confirmed" },
      { label: "Preparing", value: "preparing" },
      { label: "Dispatched", value: "dispatched" },
      { label: "Delayed", value: "delayed" },
      { label: "Delivered", value: "delivered" },
      { label: "Cancelled", value: "cancelled" },
    ],
  },
  {
    key: "payment_status",
    label: "payment statuses",
    options: [
      { label: "Pending", value: "pending" },
      { label: "Paid", value: "paid" },
      { label: "Failed", value: "failed" },
      { label: "Refunded", value: "refunded" },
      { label: "Partially refunded", value: "partially_refunded" },
    ],
  },
];

export default function OrdersPage() {
  return (
    <ResourcePage<OrderSummary>
      title="Orders"
      endpoint="/orders"
      columns={orderColumns}
      description="View and search customer orders"
      filters={orderFilters}
    />
  );
}
