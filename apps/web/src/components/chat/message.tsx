"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Avatar } from "@/components/ui/avatar";
import { Logo } from "@/components/ui/logo";
import { WorkflowPreview, type WorkflowPreviewData } from "./workflow-preview";
import { OAuthPrompt, type OAuthPromptData } from "./oauth-prompt";
import { cn } from "@/lib/utils";
import type { Message as MessageType } from "@/types/chat";

export interface MessageProps {
  message: MessageType;
}

function formatTime(dateStr: string) {
  const date = new Date(dateStr);
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

export function Message({ message }: MessageProps) {
  const [showTimestamp, setShowTimestamp] = useState(false);
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className={cn(
        "flex gap-3 group",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
      onMouseEnter={() => setShowTimestamp(true)}
      onMouseLeave={() => setShowTimestamp(false)}
    >
      {/* Avatar */}
      {isUser ? (
        <Avatar
          size="sm"
          fallback="U"
          className="shrink-0 mt-1 bg-gray-200 text-gray-700"
        />
      ) : (
        <div className="flex h-8 w-8 shrink-0 mt-1 items-center justify-center">
          <Logo variant="icon" className="h-8 w-8" />
        </div>
      )}

      {/* Bubble + attachments */}
      <div
        className={cn(
          "flex flex-col max-w-[75%] sm:max-w-[75%] max-w-[85%]",
          isUser ? "items-end" : "items-start"
        )}
      >
        <div className="relative">
          <div
            className={cn(
              "px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap break-words",
              isUser
                ? "bg-conduut-50 text-foreground rounded-2xl rounded-br-md"
                : "bg-card border border-border text-foreground rounded-2xl rounded-bl-md"
            )}
          >
            {message.content}
          </div>

          {/* Timestamp on hover */}
          <span
            className={cn(
              "absolute -bottom-5 text-[11px] text-muted-foreground whitespace-nowrap transition-opacity duration-150",
              isUser ? "right-0" : "left-0",
              showTimestamp ? "opacity-100" : "opacity-0"
            )}
          >
            {formatTime(message.createdAt)}
          </span>
        </div>

        {/* Attachments */}
        {message.attachments?.map((attachment, i) => {
          if (attachment.type === "workflow_preview") {
            return (
              <WorkflowPreview
                key={i}
                data={attachment.data as unknown as WorkflowPreviewData}
                className="w-full"
              />
            );
          }
          if (attachment.type === "oauth_prompt") {
            return (
              <OAuthPrompt
                key={i}
                data={attachment.data as unknown as OAuthPromptData}
                className="w-full"
              />
            );
          }
          return null;
        })}
      </div>
    </motion.div>
  );
}
