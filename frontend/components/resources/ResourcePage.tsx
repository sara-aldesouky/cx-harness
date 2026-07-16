"use client";

import { useCallback, useMemo, useState } from "react";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, RowData } from "@tanstack/react-table";

import { PageContainer } from "@/components/common/page-container";
import { DataTable, dataTableQueryKey } from "@/components/tables/DataTable";
import { ResourceActions } from "@/components/resources/ResourceActions";
import { ResourceHeader } from "@/components/resources/ResourceHeader";
import { ResourceToolbar } from "@/components/resources/ResourceToolbar";

export interface ResourcePageProps<TData extends RowData> {
  title: string;
  endpoint: string;
  columns: ColumnDef<TData, unknown>[];
  description?: string;
}

export function ResourcePage<TData extends RowData>({
  title,
  endpoint,
  columns,
  description,
}: ResourcePageProps<TData>) {
  const queryClient = useQueryClient();
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const queryKey = useMemo(() => dataTableQueryKey(endpoint), [endpoint]);
  const isRefreshing =
    useIsFetching({
      queryKey,
    }) > 0;

  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey });
  }, [queryClient, queryKey]);

  const handleDataUpdatedAtChange = useCallback((timestamp: number) => {
    setLastUpdatedAt(timestamp);
  }, []);

  return (
    <PageContainer>
      <ResourceHeader
        title={title}
        description={description}
        lastUpdatedAt={lastUpdatedAt}
        actions={
          <ResourceActions
            isRefreshing={isRefreshing}
            onRefresh={handleRefresh}
          />
        }
      />
      <ResourceToolbar>
        <DataTable<TData>
          endpoint={endpoint}
          columns={columns}
          onDataUpdatedAtChange={handleDataUpdatedAtChange}
        />
      </ResourceToolbar>
    </PageContainer>
  );
}
