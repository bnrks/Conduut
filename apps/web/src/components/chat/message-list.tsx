"use client";

import { useEffect } from "react";
import { ChevronDown } from "lucide-react";
import { useScrollToBottom } from "@/hooks/use-scroll-to-bottom";
import { Message } from "./message";
import { TypingIndicator } from "./typing-indicator";
import { cn } from "@/lib/utils";
import type { Message as MessageType } from "@/types/chat";

export interface MessageListProps {
  messages: MessageType[];
  isAgentTyping?: boolean;
  agentActivity?: string;
  activeClarificationMessageId?: string;
}

export function MessageList({
  messages,
  isAgentTyping,
  agentActivity,
  activeClarificationMessageId,
}: MessageListProps) {
  const { containerRef, isAtBottom, scrollToBottom } =
    useScrollToBottom<HTMLDivElement>();

  // Auto-scroll on new messages / typing start
  useEffect(() => {
    if (isAtBottom) scrollToBottom();
  }, [messages, isAgentTyping, isAtBottom, scrollToBottom]);

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto px-4 py-6 scroll-smooth"
      >
        <div className="mx-auto max-w-3xl space-y-4 pb-4">
          {messages.map((message) => (
            <Message
              key={message.id}
              message={message}
              hideInputRequests={message.id === activeClarificationMessageId}
            />
          ))}
          {isAgentTyping && (
            <div className="flex items-start gap-3">
              <div className="h-8 w-8 shrink-0" />
              <div className="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-2.5">
                <TypingIndicator activity={agentActivity} />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Scroll to bottom button */}
      {!isAtBottom && (
        <button
          onClick={scrollToBottom}
          className={cn(
            "absolute bottom-4 right-4 flex h-8 w-8 items-center justify-center",
            "rounded-full border border-border bg-card shadow-md",
            "text-muted-foreground hover:text-foreground hover:bg-muted",
            "transition-all duration-150"
          )}
          aria-label="Scroll to bottom"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
