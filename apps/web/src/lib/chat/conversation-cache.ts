import type { Message } from "@/types/chat";

interface CachedConversation {
  messages: Message[];
  provider?: string;
  model?: string;
}

const cache = new Map<string, CachedConversation>();

export function setConversationCache(id: string, messages: Message[], provider?: string, model?: string): void {
  cache.set(id, { messages, provider, model });
}

export function popConversationCache(id: string): CachedConversation | null {
  const data = cache.get(id) ?? null;
  cache.delete(id);
  return data;
}
