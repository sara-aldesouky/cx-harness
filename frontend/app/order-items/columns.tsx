"use client";

import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import type { OrderItemSummary } from "@/types";

const currencyFormatter = new Intl.NumberFormat("en-EG", {
  style: "currency",
  currency: "EGP",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

const statusVariants = {
  included: "secondary",
  missing: "destructive",
  replaced: "outline",
  refunded: "outline",
} as const;

const compactUuid = (value: string) =>
  `${value.slice(0, 8)}…${value.slice(-4)}`;

export const orderItemColumns: ColumnDef<OrderItemSummary, unknown>[] = [
  {
    accessorKey: "product_name",
    header: "Product name",
    cell: ({ getValue }) => {
      const productName = getValue<string>();
      return (
        <span
          className="block max-w-64 truncate font-medium"
          title={productName}
        >
          {productName}
        </span>
      );
    },
  },
  {
    accessorKey: "order_id",
    header: "Order ID",
    cell: ({ getValue }) => {
      const orderId = getValue<string>();
      return (
        <span className="font-mono text-xs" title={orderId}>
          {compactUuid(orderId)}
        </span>
      );
    },
  },
  {
    accessorKey: "quantity",
    header: "Quantity",
    cell: ({ getValue }) => (
      <span className="block text-right tabular-nums">
        {getValue<number>().toLocaleString("en")}
      </span>
    ),
  },
  {
    accessorKey: "unit_price",
    header: "Unit price",
    cell: ({ getValue }) => (
      <span className="tabular-nums">
        {currencyFormatter.format(Number(getValue<string>()))}
      </span>
    ),
  },
  {
    accessorKey: "item_status",
    header: "Item status",
    cell: ({ getValue }) => {
      const status = getValue<OrderItemSummary["item_status"]>();
      return (
        <Badge
          variant={
            statusVariants[status as keyof typeof statusVariants] ?? "outline"
          }
          className="capitalize"
        >
          {status}
        </Badge>
      );
    },
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ getValue }) =>
      dateTimeFormatter.format(new Date(getValue<string>())),
  },
];
