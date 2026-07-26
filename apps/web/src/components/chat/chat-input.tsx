"use client";

import { type KeyboardEvent } from "react";
import { Info, SendHorizontal } from "lucide-react";
import { useAutoResizeTextarea } from "@/hooks/use-auto-resize-textarea";
import { cn } from "@/lib/utils";
import type { ExecutionPolicy } from "@/types/chat";

export interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  value: string;
  onChange: (value: string) => void;
  executionPolicy?: ExecutionPolicy;
  executionPolicyLocked?: boolean;
  onExecutionPolicyChange?: (value: ExecutionPolicy) => void;
}

export function ChatInput({
  onSend,
  disabled,
  value,
  onChange,
  executionPolicy = "safe",
  executionPolicyLocked = false,
  onExecutionPolicyChange,
}: ChatInputProps) {
  const { ref, resize } = useAutoResizeTextarea(120);
  const executionPolicyReadOnly = executionPolicyLocked || !onExecutionPolicyChange;
  const safeModeEnabled = executionPolicy === "safe";
  const executionPolicyTooltip = safeModeEnabled
    ? "Runs a real-input sandbox preview before approval. Slower and potentially more costly, but safer."
    : "Skips the runtime sandbox and relies on static checks. Faster and cheaper, but carries more risk.";

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    onChange("");
    setTimeout(() => resize(), 0);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isEmpty = value.trim().length === 0;

  return (
    <div className="border-t border-border bg-background px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div
          className={cn(
            "rounded-xl border border-border bg-card",
            "focus-within:border-conduut-500 focus-within:ring-2 focus-within:ring-conduut-500/20",
            "transition-all duration-150"
          )}
        >
          <div className="px-3 pb-1 pt-3">
            <textarea
              ref={ref}
              value={value}
              onChange={(e) => {
                onChange(e.target.value);
                resize();
              }}
              onKeyDown={handleKeyDown}
              placeholder="Message Conduut..."
              rows={1}
              disabled={disabled}
              className={cn(
                "block w-full resize-none bg-transparent text-[15px] text-foreground",
                "placeholder:text-muted-foreground",
                "focus:outline-none disabled:opacity-50",
                "leading-relaxed py-1"
              )}
              style={{ maxHeight: 120 }}
            />
          </div>

          <div className="flex items-center justify-between gap-3 px-3 pb-2 pt-1">
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-medium text-muted-foreground">
                Safe mode
              </span>

              <label
                className={cn(
                  "relative inline-flex shrink-0 cursor-pointer items-center",
                  (disabled || executionPolicyReadOnly) && "cursor-default"
                )}
              >
                <input
                  type="checkbox"
                  className="peer sr-only"
                  checked={safeModeEnabled}
                  disabled={disabled || executionPolicyReadOnly}
                  onChange={(event) =>
                    onExecutionPolicyChange?.(event.target.checked ? "safe" : "fast")
                  }
                  aria-label="Safe mode"
                />
                <span
                  aria-hidden="true"
                  className={cn(
                    "relative h-5 w-9 rounded-full border transition-colors duration-150",
                    safeModeEnabled
                      ? "border-conduut-500 bg-conduut-500"
                      : "border-border bg-muted",
                    (disabled || executionPolicyReadOnly) && "opacity-60"
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-[2px] h-3.5 w-3.5 rounded-full bg-white shadow-sm",
                      "transition-transform duration-150",
                      safeModeEnabled ? "translate-x-[17px]" : "translate-x-[2px]"
                    )}
                  />
                </span>
              </label>

              <span className="group relative inline-flex">
                <button
                  type="button"
                  className="flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-conduut-500/50"
                  aria-label="About safe mode"
                  aria-describedby="safe-mode-tooltip"
                >
                  <Info className="h-3.5 w-3.5" />
                </button>
                <span
                  id="safe-mode-tooltip"
                  role="tooltip"
                  className={cn(
                    "pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-64 -translate-x-1/2",
                    "rounded-lg border border-border bg-card px-3 py-2 text-[11px] leading-relaxed text-card-foreground shadow-lg",
                    "invisible opacity-0 transition-opacity duration-150",
                    "group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
                  )}
                >
                  {executionPolicyTooltip}
                  {executionPolicyReadOnly
                    ? " This setting is locked for the current conversation."
                    : ""}
                </span>
              </span>
            </div>

            <button
              onClick={handleSend}
              disabled={isEmpty || disabled}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                "bg-conduut-500 text-white",
                "hover:bg-conduut-700 active:scale-95",
                "transition-all duration-150",
                "disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100"
              )}
              aria-label="Send message"
            >
              <SendHorizontal className="h-4 w-4" />
            </button>
          </div>
        </div>
        <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
          Conduut can make mistakes. Review important automations before activating.
        </p>
      </div>
    </div>
  );
}
