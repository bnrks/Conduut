"use client";

import { Clock, Play, Trash2, Zap } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Spinner } from "@/components/ui/spinner";
import type { Workflow, WorkflowStatus } from "@/types/workflow";
import { cn } from "@/lib/utils";

function formatRelativeTime(dateStr?: string): string {
  if (!dateStr) return "Never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function statusBadgeVariant(status: WorkflowStatus): "success" | "outline" {
  return status === "active" ? "success" : "outline";
}

function statusLabel(status: WorkflowStatus): string {
  return status === "active" ? "Active" : "Inactive";
}

interface WorkflowCardProps {
  workflow: Workflow;
  isRunning?: boolean;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (workflow: Workflow) => void;
  onRun?: (workflow: Workflow) => void;
  onToggle?: (workflow: Workflow) => void;
  onDelete?: (workflow: Workflow) => void;
}

export function WorkflowCard({
  workflow,
  isRunning,
  selectable = false,
  selected = false,
  onToggleSelect,
  onRun,
  onToggle,
  onDelete,
}: WorkflowCardProps) {
  return (
    <Card
      interactive
      onClick={selectable ? () => onToggleSelect?.(workflow) : undefined}
      className={cn("flex flex-col", selectable && selected && "ring-2 ring-conduut-500")}
    >
      <CardContent className="flex flex-col gap-3 p-5">
        {/* Header row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 max-w-full items-center gap-2">
            {selectable && (
              <Checkbox
                checked={selected}
                onCheckedChange={() => onToggleSelect?.(workflow)}
                onClick={(event) => event.stopPropagation()}
                aria-label={`Select ${workflow.name}`}
              />
            )}
            <div className="group relative flex min-w-0 items-center gap-2">
              <span className="block truncate text-[15px] font-medium text-foreground">
                {workflow.name}
              </span>
              <span
                role="tooltip"
                className="pointer-events-none invisible absolute left-0 top-full z-40 mt-1 max-w-xs rounded-md border border-border bg-card px-2.5 py-1.5 text-[12px] font-medium leading-snug text-foreground opacity-0 shadow-lg shadow-black/10 transition-opacity group-hover:visible group-hover:opacity-100"
              >
                {workflow.name}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge variant={statusBadgeVariant(workflow.status)}>
              {statusLabel(workflow.status)}
            </Badge>
            {!selectable && onDelete && (
              <button
                type="button"
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(workflow);
                }}
                aria-label={`Delete ${workflow.name}`}
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Description */}
        {workflow.description && (
          <p className="text-[13px] text-muted-foreground line-clamp-2 leading-relaxed">
            {workflow.description}
          </p>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border pt-1">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1 text-[12px] text-muted-foreground">
              <Zap className="h-3 w-3" />
              {workflow.nodeCount} nodes
            </span>
            <span className="flex items-center gap-1 text-[12px] text-muted-foreground tabular-nums">
              <Clock className="h-3 w-3" />
              {formatRelativeTime(workflow.lastExecutionAt)}
            </span>
          </div>

          {!selectable && (
            <div className="flex items-center gap-2">
              {onRun && (
                <button
                  type="button"
                  disabled={isRunning}
                  className={cn(
                    "flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    isRunning && "cursor-not-allowed opacity-70 hover:bg-transparent hover:text-muted-foreground"
                  )}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!isRunning) onRun(workflow);
                  }}
                >
                  {isRunning ? <Spinner size="sm" /> : <Play className="h-3.5 w-3.5" />}
                  {isRunning ? "Running…" : "Run"}
                </button>
              )}

              <button
                role="switch"
                aria-checked={workflow.status === "active"}
                onClick={(e) => {
                  e.stopPropagation();
                  onToggle?.(workflow);
                }}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  workflow.status === "active" ? "bg-conduut-500" : "bg-gray-200"
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform duration-200",
                    workflow.status === "active" ? "translate-x-4" : "translate-x-0"
                  )}
                />
              </button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
