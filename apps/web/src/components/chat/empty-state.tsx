"use client";

import { Logo } from "@/components/ui/logo";
import { cn } from "@/lib/utils";

const SUGGESTED_PROMPTS = [
  "Connect my Gmail to Slack notifications",
  "Create a weekly Google Sheets report",
  "Set up GitHub PR notifications",
  "Automate invoice processing",
];

export interface EmptyStateProps {
  onPromptClick?: (prompt: string) => void;
  className?: string;
}

export function EmptyState({ onPromptClick, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center px-4 py-12",
        className
      )}
    >
      <Logo variant="icon" className="h-14 w-14 mb-5" />
      <h2 className="text-[22px] font-medium text-foreground tracking-tight mb-2">
        How can I help you automate?
      </h2>
      <p className="text-[15px] text-muted-foreground mb-8 text-center max-w-sm">
        Describe what you want to automate and I&apos;ll build the workflow for you.
      </p>
      <div className="flex flex-wrap justify-center gap-2 max-w-xl">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onPromptClick?.(prompt)}
            className={cn(
              "rounded-full border border-border px-4 py-2",
              "text-[13px] text-conduut-500 font-medium",
              "hover:bg-conduut-50 hover:border-conduut-200",
              "active:scale-[0.97] transition-all duration-150"
            )}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
