"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Plus, Search, Workflow as WorkflowIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { WorkflowCard } from "@/components/dashboard/workflow-card";
import { useAuth } from "@/hooks/use-auth";
import type { Workflow, WorkflowStatus } from "@/types/workflow";

type StatusFilter = "all" | WorkflowStatus;

export default function WorkflowsPage() {
  const { user } = useAuth();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

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
      if (!response.ok) throw new Error("Toggle failed");
    } catch {
      toast.error("Could not update workflow status.");
      void fetchWorkflows(); // revert by re-fetching
    }
  };

  const handleDelete = async (workflow: Workflow) => {
    if (!user) return;
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
    </div>
  );
}
