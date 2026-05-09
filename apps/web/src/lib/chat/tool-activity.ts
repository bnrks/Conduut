"use client";

const TOOL_ACTIVITY_LABELS: Record<string, string> = {
  search_n8n_nodes: "Checking available n8n steps",
  get_node_schema: "Reading step requirements",
  find_workflow_template: "Looking for a matching template",
  request_user_input: "Checking what details are missing",
  list_workflows: "Checking workflows",
  get_workflow: "Loading workflow details",
  create_workflow: "Creating the workflow",
  update_workflow: "Updating the workflow",
  activate_workflow: "Activating the workflow",
  deactivate_workflow: "Deactivating the workflow",
  execute_workflow: "Running the workflow",
  analyze_workflow_readiness: "Checking whether it can run",
  inspect_execution: "Reading the run result",
  list_executions: "Checking recent runs",
  delete_workflow: "Deleting the workflow",
};

export function toolActivityLabel(tool: unknown): string {
  if (typeof tool !== "string") return "Working on it";
  return TOOL_ACTIVITY_LABELS[tool] ?? "Working on the workflow";
}
