"use client";

import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import type { OrderSummary } from "@/types";

const currencyFormatter = new Intl.NumberFormat("en-EG", {
  style: "currency",
  currency: "EGP",
  minimumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
});

const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

const formatStatus = (status: string) => status.replaceAll("_", " ");

export const orderColumns: ColumnDef<OrderSummary, unknown>[] = [
  {
    accessorKey: "order_number",
    header: "Order number",
  },
  {
    accessorKey: "customer_id",
    header: "Customer ID",
    cell: ({ getValue }) => (
      <span className="font-mono text-xs">{getValue<string>()}</span>
    ),
  },
  {
    accessorKey: "status",
    header: "Order status",
    cell: ({ getValue }) => (
      <Badge variant="secondary" className="capitalize">
        {formatStatus(getValue<string>())}
      </Badge>
    ),
  },
  {
    accessorKey: "payment_status",
    header: "Payment status",
    cell: ({ getValue }) => (
      <Badge variant="outline" className="capitalize">
        {formatStatus(getValue<string>())}
      </Badge>
    ),
  },
  {
    accessorKey: "total_amount",
    header: "Total amount",
    cell: ({ getValue }) =>
      currencyFormatter.format(Number(getValue<string>())),
  },
  {
    accessorKey: "delivery_address",
    header: "Delivery address",
    cell: ({ getValue }) => {
      const address = getValue<string>();
      return (
        <span className="block max-w-64 truncate" title={address}>
          {address}
        </span>
      );
    },
  },
  {
    accessorKey: "estimated_delivery_time",
    header: "Estimated delivery",
    cell: ({ getValue }) => {
      const value = getValue<string | null>();
      return value ? dateTimeFormatter.format(new Date(value)) : "Not set";
    },
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ getValue }) => dateFormatter.format(new Date(getValue<string>())),
  },
];
