"use client";

import { type KeyboardEvent } from "react";
import { SendHorizontal } from "lucide-react";
import { useAutoResizeTextarea } from "@/hooks/use-auto-resize-textarea";
import { TypingIndicator } from "./typing-indicator";
import { cn } from "@/lib/utils";

export interface ChatInputProps {
  onSend: (content: string) => void;
  isAgentTyping?: boolean;
  disabled?: boolean;
  value: string;
  onChange: (value: string) => void;
}

export function ChatInput({
  onSend,
  isAgentTyping,
  disabled,
  value,
  onChange,
}: ChatInputProps) {
  const { ref, resize } = useAutoResizeTextarea(120); // max ~5 lines

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    onChange("");
    // Reset height after clearing
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
      {isAgentTyping && (
        <div className="mb-2 px-1">
          <TypingIndicator />
        </div>
      )}
      <div className="mx-auto max-w-3xl">
        <div
          className={cn(
            "flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2",
            "focus-within:border-conduut-500 focus-within:ring-2 focus-within:ring-conduut-500/20",
            "transition-all duration-150"
          )}
        >
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
              "flex-1 resize-none bg-transparent text-[15px] text-foreground",
              "placeholder:text-muted-foreground",
              "focus:outline-none disabled:opacity-50",
              "leading-relaxed py-1"
            )}
            style={{ maxHeight: 120 }}
          />
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
        <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
          Conduut can make mistakes. Review important automations before
          activating.
        </p>
      </div>
    </div>
  );
}
