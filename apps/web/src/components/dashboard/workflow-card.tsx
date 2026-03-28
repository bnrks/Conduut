"use client";

import { MoreHorizontal, Zap, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

function statusBadgeVariant(
  status: WorkflowStatus
): "success" | "outline" | "error" {
  if (status === "active") return "success";
  if (status === "error") return "error";
  return "outline";
}

function statusLabel(status: WorkflowStatus): string {
  if (status === "active") return "Active";
  if (status === "error") return "Error";
  return "Inactive";
}

interface WorkflowCardProps {
  workflow: Workflow;
}

export function WorkflowCard({ workflow }: WorkflowCardProps) {
  return (
    <Card
      interactive
      className="flex flex-col"
      onClick={() => {
        console.log("Open workflow:", workflow.id);
      }}
    >
      <CardContent className="flex flex-col gap-3 p-5">
        {/* Header row */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-medium text-foreground text-[15px] truncate">
              {workflow.name}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Badge variant={statusBadgeVariant(workflow.status)}>
              {statusLabel(workflow.status)}
            </Badge>
            <button
              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                console.log("Workflow menu:", workflow.id);
              }}
              aria-label="More options"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Description */}
        {workflow.description && (
          <p className="text-[13px] text-muted-foreground line-clamp-2 leading-relaxed">
            {workflow.description}
          </p>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-1 border-t border-border">
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

          {/* Toggle switch */}
          <button
            role="switch"
            aria-checked={workflow.status === "active"}
            onClick={(e) => {
              e.stopPropagation();
              console.log("Toggle workflow:", workflow.id);
            }}
            className={cn(
              "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              workflow.status === "active"
                ? "bg-conduut-500"
                : "bg-gray-200"
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
      </CardContent>
    </Card>
  );
}
