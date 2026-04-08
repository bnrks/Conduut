"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { MessageList } from "@/components/chat/message-list";
import { EmptyState } from "@/components/chat/empty-state";
import { ChatInput } from "@/components/chat/chat-input";
import { useAuth } from "@/hooks/use-auth";
import { useModelSelector } from "@/hooks/use-model-selector";
import { streamChat } from "@/lib/chat/sse";
import type { Message, MessageAttachment } from "@/types/chat";

function createId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

export default function NewChatPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isAgentTyping, setIsAgentTyping] = useState(false);
  const { providers, selectedProvider, setSelectedProvider, models, selectedModel, setSelectedModel, loadingModels, isFavorite, toggleFavorite } = useModelSelector();

  const handleSend = async (content: string) => {
    if (!user || isAgentTyping) return;

    const token = await user.getIdToken();
    const now = new Date().toISOString();
    const userMessage: Message = {
      id: createId("user"),
      conversationId: "",
      role: "user",
      content,
      createdAt: now,
    };

    const assistantMessageId = createId("assistant");
    let assistantContent = "";
    let assistantAttachments: MessageAttachment[] = [];
    let assistantVisible = false;
    let createdConversationId = "";

    setMessages((prev) => [...prev, userMessage]);
    setIsAgentTyping(true);

    try {
      await streamChat({
        token,
        body: { content, provider: selectedProvider || undefined, model: selectedModel || undefined },
        onEvent: ({ event, data }) => {
          const streamConversationId =
            typeof data.conversation_id === "string" ? data.conversation_id : "";
          if (streamConversationId) {
            createdConversationId = streamConversationId;
          }

          if (event === "error") {
            const message = typeof data.message === "string" ? data.message : "Agent error";
            toast.error(message);
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

          setMessages((prev) => {
            const normalized: Message[] = prev.map((msg) =>
              msg.conversationId === ""
                ? { ...msg, conversationId: createdConversationId || msg.conversationId }
                : msg
            );

            const assistantMessage: Message = {
              id: assistantMessageId,
              conversationId: createdConversationId,
              role: "agent",
              content: assistantContent,
              attachments: assistantAttachments,
              createdAt: now,
            };

            const next: Message[] = assistantVisible
              ? normalized.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        content: assistantContent,
                        attachments: assistantAttachments,
                        conversationId: createdConversationId || msg.conversationId,
                      }
                    : msg
                )
              : [...normalized, assistantMessage];
            assistantVisible = true;
            return next;
          });
        },
      });

      if (createdConversationId) {
        router.replace(`/chat/${createdConversationId}`);
      }
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
        selectedProvider={selectedProvider}
        onProviderChange={setSelectedProvider}
        models={models}
        selectedModel={selectedModel}
        onModelChange={setSelectedModel}
        loadingModels={loadingModels}
        isFavorite={isFavorite}
        onToggleFavorite={(p, m) => void toggleFavorite(p, m)}
      />
    </>
  );
}
