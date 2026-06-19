"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { EmptyState } from "@/components/chat/empty-state";
import {
  ClarificationPanel,
  type ClarificationPanelData,
} from "@/components/chat/clarification-panel";
import { useAuth } from "@/hooks/use-auth";
import { streamChat } from "@/lib/chat/sse";
import { popConversationCache } from "@/lib/chat/conversation-cache";
import { normalizeMessages } from "@/lib/chat/messages";
import { toolActivityLabel } from "@/lib/chat/tool-activity";
import type { Conversation, Message, MessageAttachment } from "@/types/chat";

interface ConversationDetailResponse extends Conversation {
  messages: Message[];
}

function createId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

interface ActiveClarification {
  messageId: string;
  data: ClarificationPanelData;
}

function activeClarification(messages: Message[], isAgentTyping: boolean) {
  if (isAgentTyping) return undefined;
  const lastMessage = messages[messages.length - 1];
  if (!lastMessage || lastMessage.role === "user") return undefined;
  const attachment = lastMessage.attachments?.find(
    (item) => item.type === "user_input_request"
  );
  if (!attachment) return undefined;
  return {
    messageId: lastMessage.id,
    data: attachment.data as unknown as ClarificationPanelData,
  } satisfies ActiveClarification;
}

function appendRecentActivity(items: string[], activity: string) {
  if (items[items.length - 1] === activity) return items;
  return [...items, activity].slice(-3);
}

export default function ConversationPage() {
  const params = useParams<{ conversationId: string | string[] }>();
  const conversationId = useMemo(() => {
    const value = params.conversationId;
    return Array.isArray(value) ? value[0] || "" : value;
  }, [params.conversationId]);

  const { user } = useAuth();
  const cachedMessages = useMemo(() => popConversationCache(conversationId), [conversationId]);
  const [messages, setMessages] = useState<Message[]>(() =>
    normalizeMessages(cachedMessages ?? undefined, conversationId)
  );
  const hasCachedMessages = useRef((cachedMessages?.length ?? 0) > 0);
  const [inputValue, setInputValue] = useState("");
  const [isAgentTyping, setIsAgentTyping] = useState(false);
  const [agentActivity, setAgentActivity] = useState<string | undefined>();
  const [agentActivities, setAgentActivities] = useState<string[]>([]);

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
      if (!hasCachedMessages.current) {
        // Use updater to avoid overwriting in-flight streaming messages
        setMessages((prev) =>
          prev.length > 0 ? prev : normalizeMessages(data.messages, conversationId)
        );
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
    let doneProvider: string | undefined;
    let doneModel: string | undefined;
    let doneTier: string | undefined;
    let revealAssistantAttachments = false;

    const upsertAssistantMessage = () => {
      const visibleAttachments = revealAssistantAttachments ? assistantAttachments : [];

      setMessages((prev) => {
        const exists = prev.some((msg) => msg.id === assistantMessageId);
        if (exists) {
          return prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: assistantContent,
                  attachments: visibleAttachments,
                  provider: doneProvider ?? msg.provider,
                  model: doneModel ?? msg.model,
                  tier: doneTier ?? msg.tier,
                }
              : msg
          );
        }

        if (!assistantContent && visibleAttachments.length === 0) {
          return prev;
        }

        return [
          ...prev,
          {
            id: assistantMessageId,
            conversationId,
            role: "agent",
            content: assistantContent,
            attachments: visibleAttachments,
            createdAt: assistantCreatedAt,
            provider: doneProvider,
            model: doneModel,
            tier: doneTier,
          },
        ];
      });
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsAgentTyping(true);
    setAgentActivity(undefined);
    setAgentActivities([]);

    try {
      await streamChat({
        token,
        body: {
          content,
          conversation_id: conversationId,
        },
        onEvent: ({ event, data }) => {
          if (event === "error") {
            const message = typeof data.message === "string" ? data.message : "An error occurred. Please try again.";
            toast.error(message);
            setMessages((prev) => prev.filter((msg) => msg.id !== assistantMessageId));
            return;
          }

          if (event === "done") {
            doneProvider = typeof data.provider === "string" ? data.provider : undefined;
            doneModel = typeof data.model === "string" ? data.model : undefined;
            doneTier = typeof data.tier === "string" ? data.tier : undefined;
            revealAssistantAttachments = true;
            setAgentActivity("Finishing the response");
            setAgentActivities((prev) => appendRecentActivity(prev, "Finishing the response"));
            upsertAssistantMessage();
            return;
          }

          if (event === "tool_call") {
            const label = toolActivityLabel(data.tool);
            setAgentActivity(label);
            setAgentActivities((prev) => appendRecentActivity(prev, label));
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
            if (!revealAssistantAttachments) return;
          } else {
            return;
          }

          upsertAssistantMessage();
        },
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Message could not be sent.");
    } finally {
      setIsAgentTyping(false);
      setAgentActivity(undefined);
      setAgentActivities([]);
    }
  };

  const handlePromptClick = (prompt: string) => {
    setInputValue(prompt);
  };
  const clarification = activeClarification(messages, isAgentTyping);

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
            agentActivities={agentActivities}
            activeClarificationMessageId={clarification?.messageId}
          />
        )}
      </div>
      <div className="shrink-0">
        {clarification ? (
          <div className="px-4 pb-4">
            <div className="mx-auto max-w-3xl">
              <ClarificationPanel
                key={clarification.messageId}
                data={clarification.data}
                onSubmit={(value) => { void handleSend(value); }}
              />
            </div>
          </div>
        ) : (
          <ChatInput
            value={inputValue}
            onChange={setInputValue}
            onSend={(content) => { void handleSend(content); }}
            disabled={!user}
          />
        )}
      </div>
    </>
  );
}
