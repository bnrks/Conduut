export type MessageRole = "user" | "agent";

export interface Message {
  id: string;
  conversationId: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  attachments?: MessageAttachment[];
  provider?: string;
  model?: string;
}

export interface MessageAttachment {
  type: "workflow_preview" | "oauth_prompt" | "credential_request";
  data: Record<string, unknown>;
}

export interface Conversation {
  id: string;
  title: string;
  lastMessageAt: string;
  messageCount: number;
  createdAt: string;
  provider?: string;
  model?: string;
}
