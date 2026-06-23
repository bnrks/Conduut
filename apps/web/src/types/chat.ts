export type MessageRole = "user" | "agent" | "assistant";

export interface Message {
  id: string;
  conversationId: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  created_at?: string;
  attachments?: MessageAttachment[];
  provider?: string;
  model?: string;
  tier?: string;
  reasoningEffort?: string;
  /** Canlı düşünce (thinking) token'ları — yalnız streaming sırasında doldurulur,
   *  store'a kaydedilmez (ephemeral); reload'da gelmez. */
  thinking?: string;
}

export interface MessageAttachment {
  type:
    | "workflow_preview"
    | "artifact_preview"
    | "oauth_prompt"
    | "credential_request"
    | "user_input_request";
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
  reasoning_effort?: string;
  reasoningEffort?: string;
}
