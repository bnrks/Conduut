export type WorkflowStatus = "active" | "inactive";
export type WorkflowInputFieldType = "string" | "email" | "textarea";

export interface WorkflowInputField {
  name: string;
  label: string;
  type: WorkflowInputFieldType;
  required: boolean;
  placeholder?: string;
}

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
  inputSchema?: WorkflowInputField[];
}
