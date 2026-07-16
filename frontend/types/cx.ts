import type { CustomerReference, OrderReference } from "@/types/commerce";
import type { EvaluationSummary, ToolCallSummary } from "@/types/telemetry";

export interface ConversationSummary {
  id: string;
  customer_id: string;
  related_order_id: string | null;
  status: string;
  channel: string;
  active_model: string | null;
  started_at: string;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  customer: CustomerReference;
  related_order: OrderReference | null;
  messages: MessageSummary[];
  model_runs: ModelRunSummary[];
}

export interface MessageSummary {
  id: string;
  conversation_id: string;
  role: string;
  content: string;
  language: string | null;
  sequence_number: number;
  created_at: string;
}

export interface ModelRunSummary {
  id: string;
  conversation_id: string;
  provider: string;
  model_name: string;
  status: string;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  estimated_cost: string | null;
  temperature: string | null;
  success: boolean;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  created_at: string;
}

export interface ModelRunDetail extends ModelRunSummary {
  tool_calls: ToolCallSummary[];
  evaluations: EvaluationSummary[];
}
