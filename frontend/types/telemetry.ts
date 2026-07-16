export interface ToolCallSummary {
  id: string;
  model_run_id: string;
  tool_name: string;
  status: string;
  success: boolean;
  latency_ms: number | null;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface ToolCallDetail extends ToolCallSummary {
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown> | null;
  error_message: string | null;
}

export interface EvaluationSummary {
  id: string;
  model_run_id: string;
  evaluator_type: string;
  evaluator_name: string;
  overall_score: string | null;
  passed: boolean;
  evaluated_at: string;
  created_at: string;
}

export interface EvaluationDetail extends EvaluationSummary {
  intent_score: string | null;
  tool_score: string | null;
  tone_score: string | null;
  arabic_score: string | null;
  franco_score: string | null;
  policy_score: string | null;
  resolution_score: string | null;
  notes: string | null;
  details_json: Record<string, unknown> | null;
}
