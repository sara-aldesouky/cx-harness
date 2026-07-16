"use client";

import type { ColumnDef } from "@tanstack/react-table";

import type { CustomerSummary } from "@/types";

const dateFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
});

export const customerColumns: ColumnDef<CustomerSummary, unknown>[] = [
  {
    id: "name",
    accessorFn: (customer) => `${customer.first_name} ${customer.last_name}`,
    header: "Customer",
  },
  {
    accessorKey: "email",
    header: "Email",
  },
  {
    accessorKey: "phone",
    header: "Phone",
  },
  {
    accessorKey: "preferred_language",
    header: "Language",
  },
  {
    accessorKey: "is_active",
    header: "Status",
    cell: ({ getValue }) => (getValue<boolean>() ? "Active" : "Inactive"),
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ getValue }) => dateFormatter.format(new Date(getValue<string>())),
  },
];
