"use client";

import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardCheck,
  MessageCircle,
  MessagesSquare,
  Package,
  PackageOpen,
  Play,
  RefreshCw,
  Users,
  Wrench,
} from "lucide-react";

import { DashboardSkeleton } from "@/components/cards/dashboard-skeleton";
import { RecentConversations } from "@/components/cards/recent-conversations";
import { RecentModelRuns } from "@/components/cards/recent-model-runs";
import { RecentOrders } from "@/components/cards/recent-orders";
import { StatCard } from "@/components/cards/stat-card";
import { SystemStatusCard } from "@/components/cards/system-status-card";
import { ErrorState } from "@/components/common/error-state";
import { PageContainer } from "@/components/common/page-container";
import { SectionHeader } from "@/components/common/section-header";
import { Button } from "@/components/ui/button";
import {
  dashboardQueryKeys,
  getCustomers,
  getOverview,
  getRecentConversations,
  getRecentModelRuns,
  getRecentOrders,
} from "@/lib/api/dashboard";

const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "full",
  timeStyle: "short",
});

const stats = [
  {
    key: "customers",
    title: "Customers",
    description: "Commerce customer profiles",
    icon: Users,
  },
  {
    key: "orders",
    title: "Orders",
    description: "Tracked customer orders",
    icon: Package,
  },
  {
    key: "order_items",
    title: "Order Items",
    description: "Individual ordered products",
    icon: PackageOpen,
  },
  {
    key: "conversations",
    title: "Conversations",
    description: "Customer support threads",
    icon: MessagesSquare,
  },
  {
    key: "messages",
    title: "Messages",
    description: "Messages across conversations",
    icon: MessageCircle,
  },
  {
    key: "model_runs",
    title: "Model Runs",
    description: "Recorded model executions",
    icon: Play,
  },
  {
    key: "tool_calls",
    title: "Tool Calls",
    description: "Audited business tool calls",
    icon: Wrench,
  },
  {
    key: "evaluations",
    title: "Evaluations",
    description: "Completed model assessments",
    icon: ClipboardCheck,
  },
] as const;

export function OverviewDashboard() {
  const queryClient = useQueryClient();

  const overviewQuery = useQuery({
    queryKey: dashboardQueryKeys.overview,
    queryFn: getOverview,
  });
  const conversationsQuery = useQuery({
    queryKey: dashboardQueryKeys.conversations,
    queryFn: getRecentConversations,
  });
  const modelRunsQuery = useQuery({
    queryKey: dashboardQueryKeys.modelRuns,
    queryFn: getRecentModelRuns,
  });
  const ordersQuery = useQuery({
    queryKey: dashboardQueryKeys.orders,
    queryFn: getRecentOrders,
  });
  const customersQuery = useQuery({
    queryKey: dashboardQueryKeys.customers,
    queryFn: getCustomers,
  });

  const queries = [
    overviewQuery,
    conversationsQuery,
    modelRunsQuery,
    ordersQuery,
    customersQuery,
  ];
  const isPending = queries.some((query) => query.isPending);
  const isError = queries.some((query) => query.isError);
  const isRefreshing = queries.some((query) => query.isFetching);

  const customerNames = useMemo(
    () =>
      new Map(
        (customersQuery.data?.items ?? []).map((customer) => [
          customer.id,
          `${customer.first_name} ${customer.last_name}`,
        ]),
      ),
    [customersQuery.data?.items],
  );

  const refreshDashboard = () => {
    void queryClient.invalidateQueries({ queryKey: dashboardQueryKeys.all });
  };

  if (isPending) {
    return (
      <PageContainer>
        <SectionHeader
          title="CX Harness Dashboard"
          description="Loading the current system state."
        />
        <DashboardSkeleton />
      </PageContainer>
    );
  }

  if (isError || !overviewQuery.data) {
    return (
      <PageContainer>
        <SectionHeader
          title="CX Harness Dashboard"
          description="Live customer-experience system overview."
        />
        <ErrorState
          title="Dashboard unavailable"
          message="The live dashboard data could not be loaded."
          onRetry={refreshDashboard}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <SectionHeader
        title="CX Harness Dashboard"
        description={dateTimeFormatter.format(
          new Date(overviewQuery.dataUpdatedAt),
        )}
        action={
          <Button
            type="button"
            variant="outline"
            onClick={refreshDashboard}
            disabled={isRefreshing}
          >
            <RefreshCw
              className={isRefreshing ? "size-4 animate-spin" : "size-4"}
              aria-hidden="true"
            />
            {isRefreshing ? "Refreshing" : "Refresh"}
          </Button>
        }
      />

      <section aria-labelledby="system-statistics">
        <h2 id="system-statistics" className="sr-only">
          System statistics
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <StatCard
              key={stat.key}
              title={stat.title}
              value={overviewQuery.data[stat.key]}
              description={stat.description}
              icon={stat.icon}
            />
          ))}
        </div>
      </section>

      <section
        className="grid gap-6 xl:grid-cols-3"
        aria-label="Recent system activity"
      >
        <RecentConversations
          conversations={conversationsQuery.data?.items ?? []}
          customerNames={customerNames}
        />
        <RecentModelRuns runs={modelRunsQuery.data?.items ?? []} />
        <RecentOrders
          orders={ordersQuery.data?.items ?? []}
          customerNames={customerNames}
        />
      </section>

      <SystemStatusCard />
    </PageContainer>
  );
}
