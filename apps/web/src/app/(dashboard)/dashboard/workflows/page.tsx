"use client";

import { useState } from "react";
import Link from "next/link";
import { Plus, Search, Workflow as WorkflowIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WorkflowCard } from "@/components/dashboard/workflow-card";
import type { Workflow, WorkflowStatus } from "@/types/workflow";

const MOCK_WORKFLOWS: Workflow[] = [
  {
    id: "wf-1",
    name: "Gmail to Slack Notifications",
    description:
      "Forward important emails from Gmail to a Slack channel automatically with AI-powered summarization.",
    status: "active",
    nodeCount: 6,
    lastExecutionAt: new Date(Date.now() - 12 * 60000).toISOString(),
    executionCount: 342,
    createdAt: "2025-12-01T10:00:00Z",
    updatedAt: "2026-01-15T08:30:00Z",
  },
  {
    id: "wf-2",
    name: "Google Sheets CRM Sync",
    description:
      "Sync new contacts from Google Sheets to your CRM and send a welcome email.",
    status: "active",
    nodeCount: 4,
    lastExecutionAt: new Date(Date.now() - 3 * 3600000).toISOString(),
    executionCount: 89,
    createdAt: "2026-01-10T14:00:00Z",
    updatedAt: "2026-02-01T12:00:00Z",
  },
  {
    id: "wf-3",
    name: "GitHub Issue Tracker",
    description:
      "Create tasks in Notion whenever a new GitHub issue is opened with the 'bug' label.",
    status: "inactive",
    nodeCount: 3,
    lastExecutionAt: new Date(Date.now() - 5 * 86400000).toISOString(),
    executionCount: 12,
    createdAt: "2026-02-05T09:00:00Z",
    updatedAt: "2026-03-01T16:00:00Z",
  },
  {
    id: "wf-4",
    name: "Daily Standup Reminder",
    description:
      "Send a scheduled daily standup reminder to the team Slack channel at 9 AM.",
    status: "error",
    nodeCount: 2,
    lastExecutionAt: new Date(Date.now() - 1 * 86400000).toISOString(),
    executionCount: 56,
    createdAt: "2026-01-20T11:00:00Z",
    updatedAt: "2026-03-25T07:00:00Z",
  },
  {
    id: "wf-5",
    name: "Airtable Lead Enrichment",
    description:
      "Enrich new leads in Airtable with company data and assign to the right sales rep.",
    status: "inactive",
    nodeCount: 8,
    lastExecutionAt: undefined,
    executionCount: 0,
    createdAt: "2026-03-20T15:00:00Z",
    updatedAt: "2026-03-20T15:00:00Z",
  },
];

type StatusFilter = "all" | WorkflowStatus;

export default function WorkflowsPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const filtered = MOCK_WORKFLOWS.filter((wf) => {
    const matchesSearch =
      wf.name.toLowerCase().includes(search.toLowerCase()) ||
      (wf.description?.toLowerCase().includes(search.toLowerCase()) ?? false);
    const matchesStatus =
      statusFilter === "all" || wf.status === statusFilter;
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
          {(["all", "active", "inactive", "error"] as const).map((status) => (
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

      {/* Grid */}
      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((wf) => (
            <WorkflowCard key={wf.id} workflow={wf} />
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
