"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { MessageList } from "@/components/chat/message-list";
import { EmptyState } from "@/components/chat/empty-state";
import { ChatInput } from "@/components/chat/chat-input";
import {
  ClarificationPanel,
  type ClarificationPanelData,
} from "@/components/chat/clarification-panel";
import { useAuth } from "@/hooks/use-auth";
import { streamChat } from "@/lib/chat/sse";
import { setConversationCache } from "@/lib/chat/conversation-cache";
import { toolActivityLabel } from "@/lib/chat/tool-activity";
import {
  assistantStreamFields,
  createAssistantStreamState,
  reduceAssistantStreamEvent,
} from "@/lib/chat/stream-state";
import type { Message } from "@/types/chat";

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

export default function NewChatPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isAgentTyping, setIsAgentTyping] = useState(false);
  const [agentActivity, setAgentActivity] = useState<string | undefined>();
  const [agentActivities, setAgentActivities] = useState<string[]>([]);

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
    let assistantStream = createAssistantStreamState();
    let createdConversationId = "";
    let streamCompleted = false;

    const upsertAssistantMessage = () => {
      const fields = assistantStreamFields(assistantStream);

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
                  ...fields,
                  conversationId: createdConversationId || msg.conversationId,
                  provider: fields.provider ?? msg.provider,
                  model: fields.model ?? msg.model,
                  tier: fields.tier ?? msg.tier,
                }
              : msg
          );
        }

        if (!fields.content && !fields.thinking && fields.attachments.length === 0 && !fields.steps) {
          return normalized;
        }

        return [
          ...normalized,
          {
            id: assistantMessageId,
            conversationId: createdConversationId,
            role: "agent",
            ...fields,
            createdAt: now,
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
        body: { content },
        onEvent: (event) => {
          const result = reduceAssistantStreamEvent(assistantStream, event);
          if (!result.accepted) return;
          assistantStream = result.state;
          if (result.conversationId) createdConversationId = result.conversationId;

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
            streamCompleted = true;
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

      if (createdConversationId && streamCompleted) {
        const finalFields = assistantStreamFields(assistantStream, { ephemeral: false });
        const finalMessages: Message[] = [
          { ...userMessage, conversationId: createdConversationId },
          {
            id: assistantMessageId,
            conversationId: createdConversationId,
            role: "agent",
            ...finalFields,
            attachments:
              finalFields.attachments.length > 0 ? finalFields.attachments : undefined,
            createdAt: now,
          },
        ];
        setConversationCache(createdConversationId, finalMessages);
        router.replace(`/chat/${createdConversationId}`);
      }
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
