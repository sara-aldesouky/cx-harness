export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Overview {
  customers: number;
  orders: number;
  order_items: number;
  conversations: number;
  messages: number;
  model_runs: number;
  tool_calls: number;
  evaluations: number;
}
