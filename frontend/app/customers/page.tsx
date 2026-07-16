"use client";

import { customerColumns } from "@/app/customers/customer-columns";
import { ResourcePage } from "@/components/resources";
import type { CustomerSummary } from "@/types";

export default function CustomersPage() {
  return (
    <ResourcePage<CustomerSummary>
      title="Customers"
      endpoint="/customers"
      columns={customerColumns}
      description="View and search customers"
    />
  );
}
