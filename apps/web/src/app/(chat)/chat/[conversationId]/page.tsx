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
import { streamChat, type UserInputResponse } from "@/lib/chat/sse";
import { popConversationCache } from "@/lib/chat/conversation-cache";
import { normalizeMessages } from "@/lib/chat/messages";
import { toolActivityLabel } from "@/lib/chat/tool-activity";
import {
  assistantStreamFields,
  createAssistantStreamState,
  reduceAssistantStreamEvent,
} from "@/lib/chat/stream-state";
import type { Conversation, Message } from "@/types/chat";

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

  const handleSend = async (
    content: string,
    userInputResponse?: UserInputResponse
  ) => {
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
    let assistantStream = createAssistantStreamState();
    const assistantCreatedAt = now;

    const upsertAssistantMessage = () => {
      const fields = assistantStreamFields(assistantStream);

      setMessages((prev) => {
        const exists = prev.some((msg) => msg.id === assistantMessageId);
        if (exists) {
          return prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  ...fields,
                  provider: fields.provider ?? msg.provider,
                  model: fields.model ?? msg.model,
                  tier: fields.tier ?? msg.tier,
                }
              : msg
          );
        }

        if (!fields.content && !fields.thinking && fields.attachments.length === 0 && !fields.steps) {
          return prev;
        }

        return [
          ...prev,
          {
            id: assistantMessageId,
            conversationId,
            role: "agent",
            ...fields,
            createdAt: assistantCreatedAt,
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
          user_input_response: userInputResponse,
        },
        onEvent: (event) => {
          const result = reduceAssistantStreamEvent(assistantStream, event);
          if (!result.accepted) return;
          assistantStream = result.state;

          if (result.kind === "error") {
            toast.error(result.errorMessage);
            setMessages((prev) => prev.filter((msg) => msg.id !== assistantMessageId));
            return;
          }

          if (result.kind === "recovery") {
            const recoveryMessage = result.activity ?? "Retrying the response";
            setAgentActivity(recoveryMessage);
            setAgentActivities([recoveryMessage]);
            upsertAssistantMessage();
            return;
          }

          if (result.kind === "done") {
            const activity = result.activity ?? "Finishing the response";
            setAgentActivity(activity);
            setAgentActivities((prev) => appendRecentActivity(prev, activity));
            upsertAssistantMessage();
            return;
          }

          if (event.event === "tool_call") {
            const label = toolActivityLabel(event.data.tool);
            setAgentActivity(label);
            setAgentActivities((prev) => appendRecentActivity(prev, label));
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
                onSubmit={(payload) => {
                  void handleSend(payload.content, payload.structuredResponse);
                }}
              />
            </div>
          </div>
        ) : (
          <ChatInput
            value={inputValue}
            onChange={setInputValue}
            onSend={(content) => { void handleSend(content); }}
            disabled={!user || isAgentTyping}
          />
        )}
      </div>
    </>
  );
}
