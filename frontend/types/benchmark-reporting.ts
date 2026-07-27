export type OptionalNumber = number | string | null;

export interface BenchmarkRunListItem {
  run_id: string;
  run_key: string;
  suite_key: string;
  suite_version: string;
  suite_content_hash: string;
  model_name: string;
  provider_name: string;
  scoring_policy_key: string;
  scoring_policy_version: string;
  status: string;
  expected_test_count: number;
  stored_test_count: number;
  completed_test_count: number;
  pass_rate: OptionalNumber;
  overall_score: OptionalNumber;
  score_coverage: OptionalNumber;
  created_at: string;
  report_eligible: boolean;
}

export interface BenchmarkRunPage {
  items: BenchmarkRunListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunIdentity {
  id: string;
  run_key: string;
  model_name: string;
  provider_name: string;
  status: string;
  created_at: string;
}

export interface SegmentSummary {
  segment: string;
  case_count: number;
  pass_rate: OptionalNumber;
  task_completion_rate: OptionalNumber;
  tool_selection_accuracy: OptionalNumber;
  tool_success_rate: OptionalNumber;
  grounding_failure_rate: OptionalNumber;
  hallucination_rate: OptionalNumber;
  average_latency_ms: OptionalNumber;
}

export interface ToolSummary {
  tool_name: string;
  expected_count: number;
  selected_count: number;
  selection_precision: OptionalNumber;
  selection_recall: OptionalNumber;
  execution_attempts: number;
  successful_execution_count: number;
  business_failure_count: number;
  runtime_failure_count: number;
  average_latency_ms: OptionalNumber;
}

export interface BenchmarkRunReport {
  suite_key: string;
  suite_version: string;
  run: RunIdentity;
  completion: Record<string, OptionalNumber>;
  execution: Record<string, OptionalNumber>;
  reliability: Record<string, OptionalNumber>;
  outcomes: {
    counts: Record<string, number>;
    rates: Record<string, OptionalNumber>;
  };
  grounding: Record<string, OptionalNumber>;
  hallucination: Record<string, OptionalNumber>;
  tokens: Record<string, OptionalNumber>;
  latency: Record<string, OptionalNumber>;
  context: Record<string, unknown>;
  cost: Record<string, OptionalNumber | boolean>;
  intent: Record<string, unknown>;
  performance: {
    overall_score: OptionalNumber;
    score_coverage: OptionalNumber;
    available_dimensions: string[];
    missing_dimensions: string[];
    weighted_components: Array<Record<string, OptionalNumber>>;
  };
  quality_metrics: Array<Record<string, unknown>>;
  languages: SegmentSummary[];
  categories: SegmentSummary[];
  complexity: SegmentSummary[];
  pressure: SegmentSummary[];
  tools: ToolSummary[];
  failure_categories: Array<Record<string, unknown>>;
  failure_responsibilities: Array<Record<string, unknown>>;
  customer_turn_buckets: Array<Record<string, unknown>>;
  tool_depth_buckets: Array<Record<string, unknown>>;
}

export interface ComparisonWinner {
  dimension: string;
  available: boolean;
  winning_run_key: string | null;
  runner_up_run_key: string | null;
  difference: OptionalNumber;
  tie: boolean;
  explanation: string;
}

export interface ModelComparisonReport {
  suite_key: string;
  suite_version: string;
  scoring_policy_key: string;
  scoring_policy_version: string;
  runs: BenchmarkRunReport[];
  metric_rows: Array<{
    dimension: string;
    values_by_run: Record<string, OptionalNumber>;
    comparable: boolean;
    reason: string | null;
  }>;
  winners: ComparisonWinner[];
  cost_ranking_available: boolean;
}
