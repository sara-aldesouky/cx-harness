export interface CustomerReference {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
}

export interface OrderReference {
  id: string;
  order_number: string;
  status: string;
}

export interface CustomerSummary extends CustomerReference {
  phone: string;
  preferred_language: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomerDetail extends CustomerSummary {
  orders: OrderSummary[];
  conversations: ConversationReference[];
}

export interface OrderSummary {
  id: string;
  order_number: string;
  customer_id: string;
  status: string;
  payment_status: string;
  total_amount: string;
  delivery_address: string;
  estimated_delivery_time: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderDetail extends OrderSummary {
  customer: CustomerReference;
  items: OrderItemSummary[];
  conversations: ConversationReference[];
}

export interface OrderItemSummary {
  id: string;
  order_id: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  item_status: string;
  created_at: string;
}

export type OrderItemDetail = OrderItemSummary;

export interface ConversationReference {
  id: string;
  status: string;
  channel: string;
  started_at: string;
}
