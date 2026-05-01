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
import { setConversationCache } from "@/lib/chat/conversation-cache";
import { toolActivityLabel } from "@/lib/chat/tool-activity";
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
  const [agentActivity, setAgentActivity] = useState<string | undefined>();
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
    let createdConversationId = "";
    let doneProvider: string | undefined;
    let doneModel: string | undefined;

    setMessages((prev) => [...prev, userMessage]);
    setIsAgentTyping(true);
    setAgentActivity(undefined);

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
            const message = typeof data.message === "string" ? data.message : "An error occurred. Please try again.";
            toast.error(message);
            setMessages((prev) => prev.filter((msg) => msg.id !== assistantMessageId));
            return;
          }

          if (event === "done") {
            doneProvider = typeof data.provider === "string" ? data.provider : undefined;
            doneModel = typeof data.model === "string" ? data.model : undefined;
            setAgentActivity("Finishing the response");
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId
                  ? { ...msg, provider: doneProvider, model: doneModel }
                  : msg
              )
            );
            return;
          }

          if (event === "tool_call") {
            setAgentActivity(toolActivityLabel(data.tool));
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
            const normalized: Message[] = prev.map((msg) =>
              msg.conversationId === ""
                ? { ...msg, conversationId: createdConversationId || msg.conversationId }
                : msg
            );

            const exists = normalized.some((msg) => msg.id === assistantMessageId);
            if (exists) {
              return normalized.map((msg) =>
                msg.id === assistantMessageId
                  ? {
                      ...msg,
                      content: assistantContent,
                      attachments: assistantAttachments,
                      conversationId: createdConversationId || msg.conversationId,
                    }
                  : msg
              );
            }
            return [
              ...normalized,
              {
                id: assistantMessageId,
                conversationId: createdConversationId,
                role: "agent",
                content: assistantContent,
                attachments: assistantAttachments,
                createdAt: now,
              },
            ];
          });
        },
      });

      if (createdConversationId) {
        const finalMessages: Message[] = [
          { ...userMessage, conversationId: createdConversationId },
          {
            id: assistantMessageId,
            conversationId: createdConversationId,
            role: "agent",
            content: assistantContent,
            attachments: assistantAttachments.length > 0 ? assistantAttachments : undefined,
            createdAt: now,
            provider: doneProvider,
            model: doneModel,
          },
        ];
        setConversationCache(createdConversationId, finalMessages, selectedProvider ?? undefined, selectedModel ?? undefined);
        router.replace(`/chat/${createdConversationId}`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Message could not be sent.");
    } finally {
      setIsAgentTyping(false);
      setAgentActivity(undefined);
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
          <MessageList
            messages={messages}
            isAgentTyping={isAgentTyping}
            agentActivity={agentActivity}
          />
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
