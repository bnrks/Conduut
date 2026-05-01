"use client";

import { ExternalLink, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface WorkflowPreviewData {
  name: string;
  nodeCount: number;
  status: "active" | "inactive";
  id?: string;
}

export interface WorkflowPreviewProps {
  data: WorkflowPreviewData;
  className?: string;
}

export function WorkflowPreview({ data, className }: WorkflowPreviewProps) {
  const shortId = data.id ? data.id.slice(0, 8) : undefined;

  return (
    <div
      className={cn(
        "mt-2 flex w-full items-start gap-3 rounded-lg border border-border bg-card p-3",
        className
      )}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-conduut-50">
        <Workflow className="h-4 w-4 text-conduut-500" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[14px] font-medium text-foreground">
            Workflow saved
          </p>
          <Badge
            variant={data.status === "active" ? "success" : "outline"}
            className="px-1.5 py-0 text-[11px]"
          >
            {data.status === "active" ? "Active" : "Inactive"}
          </Badge>
        </div>
        <p className="mt-0.5 truncate text-[13px] text-foreground">
          {data.name}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <span className="text-[12px] text-muted-foreground">
            {data.nodeCount} node{data.nodeCount !== 1 ? "s" : ""}
          </span>
          {shortId && (
            <span className="font-mono text-[11px] text-muted-foreground">
              wf {shortId}
            </span>
          )}
        </div>
      </div>
      <a
        href="/dashboard/workflows"
        className="inline-flex shrink-0 items-center gap-1 text-[13px] text-conduut-500 transition-colors hover:text-conduut-700"
      >
        Dashboard
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}
