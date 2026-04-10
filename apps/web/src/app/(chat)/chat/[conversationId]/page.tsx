"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { EmptyState } from "@/components/chat/empty-state";
import { useAuth } from "@/hooks/use-auth";
import { useModelSelector } from "@/hooks/use-model-selector";
import { streamChat } from "@/lib/chat/sse";
import { popConversationCache } from "@/lib/chat/conversation-cache";
import type { Conversation, Message, MessageAttachment } from "@/types/chat";

interface ConversationDetailResponse extends Conversation {
  messages: Message[];
}

function createId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

export default function ConversationPage() {
  const params = useParams<{ conversationId: string | string[] }>();
  const conversationId = useMemo(() => {
    const value = params.conversationId;
    return Array.isArray(value) ? value[0] || "" : value;
  }, [params.conversationId]);

  const { user } = useAuth();
  const cachedData = useMemo(() => popConversationCache(conversationId), []);
  const [messages, setMessages] = useState<Message[]>(() => cachedData?.messages ?? []);
  const hasCachedMessages = useRef((cachedData?.messages?.length ?? 0) > 0);
  const [lockedProvider, setLockedProvider] = useState<string | undefined>(cachedData?.provider);
  const [lockedModel, setLockedModel] = useState<string | undefined>(cachedData?.model);
  const [inputValue, setInputValue] = useState("");
  const [isAgentTyping, setIsAgentTyping] = useState(false);
  const { providers, isFavorite, toggleFavorite } = useModelSelector();

  useEffect(() => {
    const loadConversation = async () => {
      if (!user) return;

      const token = await user.getIdToken();
      const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        toast.error("Conversation could not be loaded.");
        return;
      }

      const data = (await response.json()) as ConversationDetailResponse;
      setLockedProvider(data.provider);
      setLockedModel(data.model);
      if (!hasCachedMessages.current) {
        // Use updater to avoid overwriting in-flight streaming messages
        setMessages((prev) => (prev.length > 0 ? prev : (data.messages || [])));
        hasCachedMessages.current = true;
      }
    };

    void loadConversation();
  }, [conversationId, user]);

  const handleSend = async (content: string) => {
    if (!user || isAgentTyping) return;

    const token = await user.getIdToken();
    const now = new Date().toISOString();
    const userMessage: Message = {
      id: createId("user"),
      conversationId,
      role: "user",
      content,
      createdAt: now,
    };

    const assistantMessageId = createId("assistant");
    let assistantContent = "";
    let assistantAttachments: MessageAttachment[] = [];
    const assistantCreatedAt = now;

    setMessages((prev) => [...prev, userMessage]);
    setIsAgentTyping(true);

    try {
      await streamChat({
        token,
        body: { content, conversation_id: conversationId, provider: lockedProvider, model: lockedModel },
        onEvent: ({ event, data }) => {
          if (event === "error") {
            const message = typeof data.message === "string" ? data.message : "An error occurred. Please try again.";
            toast.error(message);
            setMessages((prev) => prev.filter((msg) => msg.id !== assistantMessageId));
            return;
          }

          if (event === "done") {
            const doneProvider = typeof data.provider === "string" ? data.provider : undefined;
            const doneModel = typeof data.model === "string" ? data.model : undefined;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId
                  ? { ...msg, provider: doneProvider, model: doneModel }
                  : msg
              )
            );
            return;
          }

          if (event === "token") {
            const text = typeof data.text === "string" ? data.text : "";
            if (!text) return;
            assistantContent += text;
          } else if (event === "attachment") {
            assistantAttachments = [
              ...assistantAttachments,
              {
                type: data.type as MessageAttachment["type"],
                data: (data.data || {}) as Record<string, unknown>,
              },
            ];
          } else {
            return;
          }

          // Pure updater: check actual state instead of closure variable
          setMessages((prev) => {
            const exists = prev.some((msg) => msg.id === assistantMessageId);
            if (exists) {
              return prev.map((msg) =>
                msg.id === assistantMessageId
                  ? { ...msg, content: assistantContent, attachments: assistantAttachments }
                  : msg
              );
            }
            return [
              ...prev,
              {
                id: assistantMessageId,
                conversationId,
                role: "agent",
                content: assistantContent,
                attachments: assistantAttachments,
                createdAt: assistantCreatedAt,
              },
            ];
          });
        },
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Message could not be sent.");
    } finally {
      setIsAgentTyping(false);
    }
  };

  const handlePromptClick = (prompt: string) => {
    setInputValue(prompt);
  };

  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden">
        {messages.length === 0 ? (
          <EmptyState onPromptClick={handlePromptClick} />
        ) : (
          <MessageList messages={messages} isAgentTyping={isAgentTyping} />
        )}
      </div>
      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSend={(content) => { void handleSend(content); }}
        disabled={!user}
        providers={providers}
        selectedProvider={lockedProvider ?? null}
        onProviderChange={() => {}}
        models={lockedModel ? [{ id: lockedModel, name: lockedModel }] : []}
        selectedModel={lockedModel ?? null}
        onModelChange={() => {}}
        loadingModels={false}
        lockedModel={true}
        isFavorite={isFavorite}
        onToggleFavorite={(p, m) => void toggleFavorite(p, m)}
      />
    </>
  );
}
