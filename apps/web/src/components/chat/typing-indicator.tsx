"use client";

import { cn } from "@/lib/utils";

export interface TypingIndicatorProps {
  className?: string;
  activity?: string;
  activities?: string[];
}

export function TypingIndicator({ className, activity, activities = [] }: TypingIndicatorProps) {
  const visibleActivities = activities.filter((item) => item.trim().length > 0);

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center gap-2">
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

      {visibleActivities.length > 0 && (
        <div className="min-w-[230px] rounded-lg bg-muted/50 px-3 py-2">
          <p className="mb-1 text-[11px] font-medium text-muted-foreground">
            Progress
          </p>
          <ol className="space-y-1">
            {visibleActivities.map((item, index) => {
              const isCurrent = index === visibleActivities.length - 1;
              return (
                <li key={`${item}-${index}`} className="flex items-center gap-2">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 shrink-0 rounded-full",
                      isCurrent ? "bg-conduut-500" : "bg-muted-foreground/40"
                    )}
                  />
                  <span
                    className={cn(
                      "text-[12px] leading-snug",
                      isCurrent ? "text-foreground" : "text-muted-foreground"
                    )}
                  >
                    {item}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}
