"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Copy, Check } from "lucide-react";
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

/* ── Copy button for code blocks ── */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-all",
        copied
          ? "bg-green-500/20 text-green-400"
          : "bg-white/10 text-gray-400 hover:bg-white/20 hover:text-gray-200"
      )}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/* ── Markdown renderer (agent only) ── */
function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        // Code blocks with header + copy button
        pre({ children, ...props }) {
          // Extract raw text from code element
          const codeEl = (children as React.ReactElement<{ children?: React.ReactNode }>);
          const rawText =
            typeof codeEl?.props?.children === "string"
              ? codeEl.props.children
              : "";

          // Extract language from className
          const className = (codeEl?.props as { className?: string })?.className ?? "";
          const lang = className.replace(/^language-/, "");

          return (
            <div className="group relative">
              {/* Header bar */}
              <div className="flex items-center justify-between bg-[#0d0d0f] px-3.5 py-2 rounded-t-[7px] border-b border-white/10">
                <span className="text-[11px] font-medium text-gray-500">
                  {lang || "code"}
                </span>
                <CopyButton text={rawText} />
              </div>
              <pre {...props}>{children}</pre>
            </div>
          );
        },
        // Remove margin from pre inside the wrapper div
        code({ className, children, ...props }) {
          const isInline = !className;
          if (isInline) {
            return <code className={className} {...props}>{children}</code>;
          }
          return <code className={className} {...props}>{children}</code>;
        },
      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  );
}

export function Message({ message }: MessageProps) {
  const [showTimestamp, setShowTimestamp] = useState(false);
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className={cn("flex gap-3 group", isUser ? "flex-row-reverse" : "flex-row")}
      onMouseEnter={() => setShowTimestamp(true)}
      onMouseLeave={() => setShowTimestamp(false)}
    >
      {/* Avatar */}
      {isUser ? (
        <Avatar size="sm" fallback="U" className="shrink-0 mt-1 bg-gray-200 text-gray-700" />
      ) : (
        <div className="flex h-8 w-8 shrink-0 mt-1 items-center justify-center">
          <Logo variant="icon" className="h-8 w-8" />
        </div>
      )}

      {/* Bubble + attachments */}
      <div className={cn("flex flex-col max-w-[75%]", isUser ? "items-end" : "items-start")}>
        <div className="relative">
          <div
            className={cn(
              "px-4 py-2.5 text-[15px] leading-relaxed break-words",
              isUser
                ? "bg-conduut-50 text-foreground rounded-2xl rounded-br-md whitespace-pre-wrap"
                : "bg-card border border-border text-foreground rounded-2xl rounded-bl-md"
            )}
          >
            {isUser ? message.content : <MarkdownContent content={message.content} />}
          </div>

          {/* Timestamp + model info on hover */}
          <div
            className={cn(
              "absolute -bottom-5 flex items-center gap-1.5 whitespace-nowrap transition-opacity duration-150",
              isUser ? "right-0" : "left-0",
              showTimestamp ? "opacity-100" : "opacity-0"
            )}
          >
            {!isUser && message.model && (
              <span className="text-[11px] text-muted-foreground/70">
                {message.provider && <span className="font-medium">{message.provider}</span>}
                {message.provider && message.model && <span className="mx-0.5">/</span>}
                {message.model}
              </span>
            )}
            {!isUser && message.model && (
              <span className="text-muted-foreground/40 text-[11px]">·</span>
            )}
            <span className="text-[11px] text-muted-foreground">
              {formatTime(message.createdAt)}
            </span>
          </div>
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
