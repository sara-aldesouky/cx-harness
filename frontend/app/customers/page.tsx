"use client";

import { DataTable } from "@/components/tables";
import { customerColumns } from "@/app/customers/customer-columns";
import { PageContainer } from "@/components/common/page-container";
import type { CustomerSummary } from "@/types";

export default function CustomersPage() {
  return (
    <PageContainer>
      <DataTable<CustomerSummary>
        endpoint="/customers"
        columns={customerColumns}
        title="Customers"
        getRowId={(customer) => customer.id}
      />
    </PageContainer>
  );
}
