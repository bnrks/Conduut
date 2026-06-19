import type { Message } from "@/types/chat";

const cache = new Map<string, Message[]>();

export function setConversationCache(id: string, messages: Message[]): void {
  cache.set(id, messages);
}

export function popConversationCache(id: string): Message[] | null {
  const data = cache.get(id) ?? null;
  cache.delete(id);
  return data;
}
