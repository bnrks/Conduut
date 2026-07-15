import type { ExecutionReference } from "@/lib/chat/sse";

const STORAGE_KEY = "conduut:pending-execution-repair";

export function setPendingExecutionRepair(reference: ExecutionReference): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(reference));
}

export function consumePendingExecutionRepair(): ExecutionReference | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  sessionStorage.removeItem(STORAGE_KEY);

  try {
    const value = JSON.parse(raw) as Partial<ExecutionReference>;
    if (
      typeof value.execution_id === "string" &&
      value.execution_id.length > 0 &&
      value.intent === "diagnose_and_fix"
    ) {
      return {
        execution_id: value.execution_id,
        intent: value.intent,
        workflow_name:
          typeof value.workflow_name === "string" && value.workflow_name.trim()
            ? value.workflow_name.trim()
            : undefined,
      };
    }
  } catch {
    // Invalid or stale handoff data is discarded after the one read above.
  }
  return null;
}
