"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Plus, Search, Workflow as WorkflowIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { WorkflowCard } from "@/components/dashboard/workflow-card";
import { useAuth } from "@/hooks/use-auth";
import type { Workflow, WorkflowInputField, WorkflowStatus } from "@/types/workflow";

type StatusFilter = "all" | WorkflowStatus;

async function getErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => null) as {
    detail?: { message?: string } | string;
    message?: string;
  } | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  if (typeof payload?.message === "string") return payload.message;
  return fallback;
}

export default function WorkflowsPage() {
  const { user } = useAuth();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [runWorkflow, setRunWorkflow] = useState<Workflow | null>(null);
  const [runValues, setRunValues] = useState<Record<string, string>>({});
  const [runningWorkflowId, setRunningWorkflowId] = useState<string | null>(null);

  const fetchWorkflows = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch("/api/workflows", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Failed to fetch workflows");
      const data = (await response.json()) as { workflows: Workflow[] };
      setWorkflows(data.workflows ?? []);
    } catch {
      toast.error("Workflows could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void fetchWorkflows();
  }, [fetchWorkflows]);

  const handleToggle = async (workflow: Workflow) => {
    if (!user) return;
    const action = workflow.status === "active" ? "deactivate" : "activate";
    // Optimistic update
    setWorkflows((prev) =>
      prev.map((wf) =>
        wf.id === workflow.id
          ? { ...wf, status: action === "activate" ? "active" : "inactive" }
          : wf
      )
    );
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}?action=${action}`,
        {
          method: "PATCH",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Could not update workflow status."));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update workflow status.");
      void fetchWorkflows(); // revert by re-fetching
    }
  };

  const handleDelete = async (workflow: Workflow) => {
    if (!user) return;
    const confirmed = window.confirm(`Delete "${workflow.name}"?`);
    if (!confirmed) return;

    // Optimistic update
    setWorkflows((prev) => prev.filter((wf) => wf.id !== workflow.id));
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) throw new Error("Delete failed");
      toast.success(`"${workflow.name}" deleted.`);
    } catch {
      toast.error("Could not delete workflow.");
      void fetchWorkflows(); // revert
    }
  };

  const submitWorkflowRun = async (workflow: Workflow, input: Record<string, string>) => {
    if (!user) return;
    setRunningWorkflowId(workflow.id);
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}?action=run`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ input, source: "dashboard" }),
        }
      );
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Could not run workflow."));
      }
      const result = (await response.json().catch(() => null)) as {
        status?: string;
        summary?: string;
      } | null;
      toast.success(result?.summary || `Workflow ${result?.status || "triggered"}.`);
      setRunWorkflow(null);
      setRunValues({});
      void fetchWorkflows();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not run workflow.");
    } finally {
      setRunningWorkflowId(null);
    }
  };

  const handleRun = (workflow: Workflow) => {
    const schema = workflow.inputSchema ?? [];
    if (schema.length === 0) {
      void submitWorkflowRun(workflow, {});
      return;
    }
    setRunWorkflow(workflow);
    setRunValues(
      Object.fromEntries(schema.map((field) => [field.name, runValues[field.name] ?? ""]))
    );
  };

  const handleRunSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!runWorkflow) return;
    const missing = (runWorkflow.inputSchema ?? []).find(
      (field) => field.required && !runValues[field.name]?.trim()
    );
    if (missing) {
      toast.error(`${missing.label} is required.`);
      return;
    }
    void submitWorkflowRun(runWorkflow, runValues);
  };

  const renderRunField = (field: WorkflowInputField) => {
    const value = runValues[field.name] ?? "";
    const commonProps = {
      id: `run-${field.name}`,
      name: field.name,
      value,
      placeholder: field.placeholder,
      required: field.required,
      onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setRunValues((prev) => ({ ...prev, [field.name]: event.target.value })),
    };
    if (field.type === "textarea") {
      return <Textarea {...commonProps} rows={5} className="text-[14px]" />;
    }
    return (
      <Input
        {...commonProps}
        type={field.type === "email" ? "email" : "text"}
        className="h-9 text-[14px]"
      />
    );
  };

  const filtered = workflows.filter((wf) => {
    const matchesSearch =
      wf.name.toLowerCase().includes(search.toLowerCase()) ||
      (wf.description?.toLowerCase().includes(search.toLowerCase()) ?? false);
    const matchesStatus = statusFilter === "all" || wf.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-medium text-foreground">Workflows</h1>
        <Link href="/chat">
          <Button size="sm" className="gap-1.5">
            <Plus className="h-4 w-4" />
            New Workflow
          </Button>
        </Link>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search workflows..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-[14px]"
          />
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-card">
          {(["all", "active", "inactive"] as const).map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1 rounded-md text-[13px] font-medium transition-colors capitalize ${
                statusFilter === status
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {status === "all" ? "All" : status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      ) : filtered.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((wf) => (
            <WorkflowCard
              key={wf.id}
              workflow={wf}
              onRun={(w) => handleRun(w)}
              onToggle={(w) => void handleToggle(w)}
              onDelete={(w) => void handleDelete(w)}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted mb-4">
            <WorkflowIcon className="h-8 w-8 text-muted-foreground" />
          </div>
          <h2 className="text-[16px] font-medium text-foreground mb-1">
            {search || statusFilter !== "all"
              ? "No matching workflows"
              : "No workflows yet"}
          </h2>
          <p className="text-[14px] text-muted-foreground mb-6 max-w-xs">
            {search || statusFilter !== "all"
              ? "Try adjusting your search or filter."
              : "Start a conversation with the AI agent to create your first workflow."}
          </p>
          {!search && statusFilter === "all" && (
            <Link href="/chat">
              <Button size="sm">
                <Plus className="h-4 w-4" />
                Create your first workflow
              </Button>
            </Link>
          )}
        </div>
      )}

      {runWorkflow && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workflow-run-title"
          onClick={() => {
            if (!runningWorkflowId) setRunWorkflow(null);
          }}
        >
          <form
            className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-xl"
            onClick={(event) => event.stopPropagation()}
            onSubmit={handleRunSubmit}
          >
            <div className="mb-4">
              <h2 id="workflow-run-title" className="text-[16px] font-medium text-foreground">
                Run {runWorkflow.name}
              </h2>
            </div>
            <div className="flex flex-col gap-3">
              {(runWorkflow.inputSchema ?? []).map((field) => (
                <label key={field.name} className="flex flex-col gap-1.5">
                  <span className="text-[13px] font-medium text-foreground">
                    {field.label}
                  </span>
                  {renderRunField(field)}
                </label>
              ))}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={runningWorkflowId === runWorkflow.id}
                onClick={() => setRunWorkflow(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={runningWorkflowId === runWorkflow.id}>
                {runningWorkflowId === runWorkflow.id ? "Running..." : "Run"}
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
