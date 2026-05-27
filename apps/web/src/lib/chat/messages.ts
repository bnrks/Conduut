"use client";

import type { Message, MessageAttachment, MessageRole } from "@/types/chat";

type RawMessage = Partial<Message> & {
  conversation_id?: string;
  created_at?: string;
  reasoning_effort?: string;
  attachments?: MessageAttachment[] | null;
};

function normalizeRole(role: unknown): MessageRole {
  if (role === "user") return "user";
  if (role === "assistant") return "agent";
  return "agent";
}

export function normalizeMessage(
  message: RawMessage,
  fallbackConversationId = ""
): Message {
  return {
    id: typeof message.id === "string" ? message.id : crypto.randomUUID(),
    conversationId:
      typeof message.conversationId === "string"
        ? message.conversationId
        : typeof message.conversation_id === "string"
          ? message.conversation_id
          : fallbackConversationId,
    role: normalizeRole(message.role),
    content: typeof message.content === "string" ? message.content : "",
    createdAt:
      typeof message.createdAt === "string"
        ? message.createdAt
        : typeof message.created_at === "string"
          ? message.created_at
          : new Date().toISOString(),
    created_at: typeof message.created_at === "string" ? message.created_at : undefined,
    attachments: Array.isArray(message.attachments) ? message.attachments : undefined,
    provider: typeof message.provider === "string" ? message.provider : undefined,
    model: typeof message.model === "string" ? message.model : undefined,
    reasoningEffort:
      typeof message.reasoningEffort === "string"
        ? message.reasoningEffort
        : typeof message.reasoning_effort === "string"
          ? message.reasoning_effort
          : undefined,
  };
}

export function normalizeMessages(
  messages: RawMessage[] | undefined,
  fallbackConversationId = ""
): Message[] {
  if (!Array.isArray(messages)) return [];
  return messages.map((message) => normalizeMessage(message, fallbackConversationId));
}
