"use client";

import { Workflow } from "lucide-react";
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
  return (
    <div
      className={cn(
        "border border-border rounded-lg p-3 flex items-center gap-3 bg-card mt-2",
        className
      )}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-conduut-50">
        <Workflow className="h-4 w-4 text-conduut-500" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-medium text-[14px] text-foreground truncate">
          {data.name}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[12px] text-muted-foreground">
            {data.nodeCount} node{data.nodeCount !== 1 ? "s" : ""}
          </span>
          <Badge
            variant={data.status === "active" ? "success" : "outline"}
            className="text-[11px] py-0 px-1.5"
          >
            {data.status === "active" ? "Active" : "Inactive"}
          </Badge>
        </div>
      </div>
      <a
        href={data.id ? `/dashboard/workflows/${data.id}` : "/dashboard/workflows"}
        className="text-[13px] text-conduut-500 hover:text-conduut-700 whitespace-nowrap transition-colors"
      >
        Open in Dashboard
      </a>
    </div>
  );
}
