export type WorkflowStatus = "active" | "inactive";

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: WorkflowStatus;
  nodeCount: number;
  lastExecutionAt?: string;
  executionCount: number;
  createdAt: string;
  updatedAt: string;
}
