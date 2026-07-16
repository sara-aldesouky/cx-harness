import { apiClient } from "@/lib/api/client";
import type {
  ConversationSummary,
  CustomerSummary,
  ModelRunSummary,
  OrderSummary,
  Overview,
  PaginatedResponse,
} from "@/types";

export const dashboardQueryKeys = {
  all: ["dashboard"] as const,
  overview: ["dashboard", "overview"] as const,
  conversations: ["dashboard", "conversations", 5] as const,
  modelRuns: ["dashboard", "model-runs", 5] as const,
  orders: ["dashboard", "orders", 5] as const,
  customers: ["dashboard", "customers", 100] as const,
};

async function getResource<T>(path: string): Promise<T> {
  const response = await apiClient.get<T>(path);
  return response.data;
}

export function getOverview(): Promise<Overview> {
  return getResource<Overview>("/overview");
}

export function getRecentConversations(): Promise<
  PaginatedResponse<ConversationSummary>
> {
  return getResource("/conversations?limit=5&offset=0");
}

export function getRecentModelRuns(): Promise<
  PaginatedResponse<ModelRunSummary>
> {
  return getResource("/model-runs?limit=5&offset=0");
}

export function getRecentOrders(): Promise<PaginatedResponse<OrderSummary>> {
  return getResource("/orders?limit=5&offset=0");
}

export function getCustomers(): Promise<PaginatedResponse<CustomerSummary>> {
  return getResource("/customers?limit=100&offset=0");
}
