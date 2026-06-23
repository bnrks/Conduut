"use client";

import { useEffect } from "react";
import { ChevronDown } from "lucide-react";
import { useScrollToBottom } from "@/hooks/use-scroll-to-bottom";
import { Logo } from "@/components/ui/logo";
import { Message } from "./message";
import { TypingIndicator } from "./typing-indicator";
import { cn } from "@/lib/utils";
import type { Message as MessageType } from "@/types/chat";

export interface MessageListProps {
  messages: MessageType[];
  isAgentTyping?: boolean;
  agentActivity?: string;
  agentActivities?: string[];
  activeClarificationMessageId?: string;
}

export function MessageList({
  messages,
  isAgentTyping,
  agentActivity,
  agentActivities,
  activeClarificationMessageId,
}: MessageListProps) {
  const { containerRef, isAtBottom, scrollToBottom } =
    useScrollToBottom<HTMLDivElement>();

  // Auto-scroll on new messages / typing start
  useEffect(() => {
    if (isAtBottom) scrollToBottom();
  }, [messages, isAgentTyping, isAtBottom, scrollToBottom]);

  // Cevap metni akmaya başlayınca ayrı "Conduut is thinking" göstergesini gizle —
  // artık mesajın kendisi (ve düşünce paneli) aktiviteyi gösteriyor. Düşünme/araç
  // fazında düz metin olarak görünür (balon değil).
  const lastMessage = messages[messages.length - 1];
  const answerStreaming =
    !!isAgentTyping &&
    lastMessage?.role !== "user" &&
    (lastMessage?.content?.trim().length ?? 0) > 0;
  const showTypingIndicator = !!isAgentTyping && !answerStreaming;

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto px-4 py-6 scroll-smooth"
      >
        <div className="mx-auto max-w-3xl space-y-4 pb-4">
          {messages.map((message, i) => (
            <Message
              key={message.id}
              message={message}
              hideInputRequests={message.id === activeClarificationMessageId}
              isStreaming={
                !!isAgentTyping &&
                i === messages.length - 1 &&
                message.role !== "user"
              }
            />
          ))}
          {showTypingIndicator && (
            <div className="flex items-start gap-3">
              <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center">
                <Logo variant="icon" className="h-8 w-8" />
              </div>
              <div className="pt-1.5">
                <TypingIndicator activity={agentActivity} activities={agentActivities} />
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
