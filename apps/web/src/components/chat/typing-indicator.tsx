"use client";

import { cn } from "@/lib/utils";

export interface TypingIndicatorProps {
  className?: string;
  activity?: string;
}

export function TypingIndicator({ className, activity }: TypingIndicatorProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="flex items-center gap-1">
        <span
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce"
          style={{ animationDelay: "0ms", animationDuration: "1s" }}
        />
        <span
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce"
          style={{ animationDelay: "160ms", animationDuration: "1s" }}
        />
        <span
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce"
          style={{ animationDelay: "320ms", animationDuration: "1s" }}
        />
      </div>
      <span className="text-[13px] text-muted-foreground">
        {activity || "Conduut is thinking..."}
      </span>
    </div>
  );
}
