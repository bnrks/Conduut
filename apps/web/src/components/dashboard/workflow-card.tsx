"use client";

import { useEffect, useRef, useState } from "react";
import { Clock, MoreHorizontal, Play, Power, Trash2, Zap } from "lucide-react";
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

function statusBadgeVariant(status: WorkflowStatus): "success" | "outline" {
  return status === "active" ? "success" : "outline";
}

function statusLabel(status: WorkflowStatus): string {
  return status === "active" ? "Active" : "Inactive";
}

interface WorkflowCardProps {
  workflow: Workflow;
  onRun?: (workflow: Workflow) => void;
  onToggle?: (workflow: Workflow) => void;
  onDelete?: (workflow: Workflow) => void;
}

export function WorkflowCard({ workflow, onRun, onToggle, onDelete }: WorkflowCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  const toggleLabel = workflow.status === "active" ? "Deactivate" : "Activate";

  return (
    <Card interactive className="flex flex-col">
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
            {(onRun || onToggle || onDelete) && (
              <div ref={menuRef} className="relative">
                <button
                  type="button"
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors",
                    "hover:bg-muted hover:text-foreground",
                    menuOpen && "bg-muted text-foreground"
                  )}
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuOpen((open) => !open);
                  }}
                  aria-label="Workflow actions"
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>

                {menuOpen && (
                  <div
                    role="menu"
                    className="absolute right-0 top-full z-30 mt-1.5 min-w-[150px] overflow-hidden rounded-lg border border-border bg-card py-1 shadow-lg shadow-black/5"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {onRun && (
                      <button
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-foreground transition-colors hover:bg-muted"
                        onClick={() => {
                          setMenuOpen(false);
                          onRun(workflow);
                        }}
                      >
                        <Play className="h-3.5 w-3.5 text-muted-foreground" />
                        Run
                      </button>
                    )}
                    {onToggle && (
                      <button
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-foreground transition-colors hover:bg-muted"
                        onClick={() => {
                          setMenuOpen(false);
                          onToggle(workflow);
                        }}
                      >
                        <Power className="h-3.5 w-3.5 text-muted-foreground" />
                        {toggleLabel}
                      </button>
                    )}
                    {onDelete && (
                      <button
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-red-600 transition-colors hover:bg-red-50"
                        onClick={() => {
                          setMenuOpen(false);
                          onDelete(workflow);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </button>
                    )}
                  </div>
                )}
              </div>
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
      </CardContent>
    </Card>
  );
}
