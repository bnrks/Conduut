"use client";

import { memo, useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Copy, Check } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Logo } from "@/components/ui/logo";
import { ArtifactPreview } from "@/components/artifacts/artifact-preview";
import { WorkflowPreview, type WorkflowPreviewData } from "./workflow-preview";
import { OAuthPrompt, type OAuthPromptData } from "./oauth-prompt";
import { CredentialRequest, type CredentialRequestData } from "./credential-request";
import { ThinkingPanel } from "./thinking-panel";
import { cn } from "@/lib/utils";
import type { Message as MessageType } from "@/types/chat";
import type { ArtifactPreviewData } from "@/types/artifact";

export interface MessageProps {
  message: MessageType;
  hideInputRequests?: boolean;
  /** Bu mesaj şu an stream ediliyor mu? Streaming sırasında syntax-highlight
   *  ertelenir (her token'da tüm metni yeniden boyamamak için). */
  isStreaming?: boolean;
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

/* ── Kelime kelime fade-in (yalnız streaming) ──
   String içeriği boşlukları koruyarak kelimelere böler, her kelimeyi tek bir
   fade-in span'ine sarar. index key append-only stream'de stabil olduğundan
   sadece YENİ eklenen kelime mount olup animasyon alır; mevcutlar tekrar oynamaz.
   String olmayan (inline markdown'lı) içerik olduğu gibi render edilir. */
function FadeWords({ children }: { children: React.ReactNode }) {
  if (typeof children !== "string") return <>{children}</>;
  return (
    <>
      {children.split(/(\s+)/).map((part, i) =>
        part === "" || /^\s+$/.test(part) ? (
          part
        ) : (
          <span key={i} className="fade-in-word">
            {part}
          </span>
        )
      )}
    </>
  );
}

/* ── Markdown renderer (agent only) ──
   memo: içerik değişmedikçe (ör. hover/timestamp re-render'ı) yeniden parse
   etme. streaming: aktif token akışı sırasında rehypeHighlight'ı (highlight.js,
   her render'da tüm metni yeniden boyar → mesaj uzadıkça O(N²)) atla; mesaj
   tamamlanınca bir kez highlight'la. */
const MarkdownContent = memo(function MarkdownContent({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  return (
    <div className="markdown">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={streaming ? [] : [rehypeHighlight]}
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
        // Stream sırasında paragraf/liste metnini kelime kelime fade-in yap
        // (canlı markdown korunur; kod blokları yukarıdaki pre/code'da kalır).
        ...(streaming
          ? {
              p: ({ children }: { children?: React.ReactNode }) => (
                <p>
                  <FadeWords>{children}</FadeWords>
                </p>
              ),
              li: ({ children }: { children?: React.ReactNode }) => (
                <li>
                  <FadeWords>{children}</FadeWords>
                </li>
              ),
            }
          : {}),
      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  );
});

function UserInputSummary({ data }: { data: Record<string, unknown> }) {
  const question = typeof data.question === "string" ? data.question : "Conduut asked a question";
  const missingFields = Array.isArray(data.missingFields)
    ? data.missingFields
        .filter((field): field is string => typeof field === "string" && field.trim().length > 0)
        .map((field) => field.trim())
    : [];

  return (
    <div className="mt-1 rounded-lg border border-border bg-muted/40 px-3 py-2 text-[13px] text-muted-foreground">
      <div className="flex items-start gap-2">
        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-conduut-500" />
        <div className="min-w-0">
          <p className="font-medium text-foreground">Conduut asked for details</p>
          <p className="line-clamp-2 break-words">{question}</p>
          {missingFields.length > 0 && (
            <p className="mt-1 truncate">
              Needed: {missingFields.join(", ")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageBase({ message, hideInputRequests = false, isStreaming = false }: MessageProps) {
  const [showTimestamp, setShowTimestamp] = useState(false);
  const isUser = message.role === "user";
  const inputRequestAttachments =
    message.attachments?.filter((attachment) => attachment.type === "user_input_request") ?? [];
  const visibleAttachments =
    message.attachments?.filter((attachment) => attachment.type !== "user_input_request") ?? [];
  const inputRequests = hideInputRequests ? [] : inputRequestAttachments;
  const hasText = message.content.trim().length > 0 && inputRequestAttachments.length === 0;
  const hasThinking = !isUser && !!message.thinking;

  if (!hasText && !hasThinking && inputRequests.length === 0 && visibleAttachments.length === 0) {
    return null;
  }

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
        {hasThinking && (
          <ThinkingPanel content={message.thinking ?? ""} answerStarted={hasText} />
        )}
        {hasText && (
          <div className="relative">
            <div
              className={cn(
                "px-4 py-2.5 text-[15px] leading-relaxed break-words",
                isUser
                  ? "bg-conduut-50 text-foreground rounded-2xl rounded-br-md whitespace-pre-wrap"
                  : "bg-card border border-border text-foreground rounded-2xl rounded-bl-md"
              )}
            >
              {isUser ? (
                message.content
              ) : (
                <MarkdownContent content={message.content} streaming={isStreaming} />
              )}
            </div>

            {/* Timestamp on hover */}
            <div
              className={cn(
                "absolute -bottom-5 flex items-center gap-1.5 whitespace-nowrap transition-opacity duration-150",
                isUser ? "right-0" : "left-0",
                showTimestamp ? "opacity-100" : "opacity-0"
              )}
            >
              <span className="text-[11px] text-muted-foreground">
                {formatTime(message.createdAt)}
              </span>
            </div>
          </div>
        )}

        {/* Debug: which tier/model answered (assistant only) */}
        {!isUser && message.model && (
          <span className="mt-1 font-mono text-[10px] text-muted-foreground/70">
            {message.tier ? `${message.tier} · ` : ""}
            {message.model}
          </span>
        )}

        {inputRequests.map((attachment, i) => (
          <UserInputSummary key={`input-${i}`} data={attachment.data} />
        ))}

        {/* Attachments */}
        {visibleAttachments.map((attachment, i) => {
          if (attachment.type === "workflow_preview") {
            return (
              <WorkflowPreview
                key={i}
                data={attachment.data as unknown as WorkflowPreviewData}
                className="w-full"
              />
            );
          }
          if (attachment.type === "artifact_preview") {
            return (
              <ArtifactPreview
                key={i}
                data={attachment.data as unknown as ArtifactPreviewData}
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
          if (attachment.type === "credential_request") {
            return (
              <CredentialRequest
                key={i}
                data={attachment.data as unknown as CredentialRequestData}
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

/* memo: MessageList her token'da yeni bir messages dizisi set ediyor, ama
   upsertAssistantMessage değişmeyen mesajları aynı referansla döndürüyor →
   memo sayesinde sadece stream edilen (referansı değişen) mesaj yeniden render
   olur; geçmiş mesajların markdown'ı her token'da yeniden parse edilmez. */
export const Message = memo(MessageBase);
