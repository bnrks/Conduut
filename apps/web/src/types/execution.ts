export type ExecutionStatus =
  | "success"
  | "error"
  | "running"
  | "waiting"
  | "canceled"
  | "cancelled"
  | "unknown";

export interface ExecutionSummary {
  id: string;
  workflow_id: string;
  workflow_name: string | null;
  status: ExecutionStatus;
  mode: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface ExecutionDetail extends ExecutionSummary {
  summary: string | null;
  failed_node: string | null;
  error: string | null;
}

export interface ExecutionListResponse {
  executions: ExecutionSummary[];
  next_cursor: string | null;
}
