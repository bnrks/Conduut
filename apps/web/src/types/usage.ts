export interface TokenUsageTotals {
  agent_runs: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  model_requests: number;
  tool_calls: number;
}

export interface DailyTokenUsage {
  date: string;
  agent_runs: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface ModelTokenUsage extends TokenUsageTotals {
  provider: string;
  model: string;
  tier: string;
}

export interface UsageSummaryResponse {
  days: 1 | 7 | 30 | 90;
  starts_at: string;
  ends_at: string;
  totals: TokenUsageTotals;
  daily: DailyTokenUsage[];
  by_model: ModelTokenUsage[];
  scope: "completed_agent_runs";
}
