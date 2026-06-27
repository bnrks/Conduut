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
import type { Message, MessageAttachment, AgentStep } from "@/types/chat";

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
    let assistantContent = "";
    const assistantSteps: AgentStep[] = [];

    const addTokenStep = (text: string) => {
      const last = assistantSteps[assistantSteps.length - 1];
      if (!last || last.kind !== "text") assistantSteps.push({ kind: "text", text: "" });
      (assistantSteps[assistantSteps.length - 1] as { kind: "text"; text: string }).text += text;
    };
    const addActivityStep = (tool: string) => {
      const last = assistantSteps[assistantSteps.length - 1];
      if (!last || last.kind !== "activity") assistantSteps.push({ kind: "activity", actions: [] });
      (assistantSteps[assistantSteps.length - 1] as { kind: "activity"; actions: string[] }).actions.push(tool);
    };
    const cloneSteps = (): AgentStep[] | undefined =>
      assistantSteps.length
        ? assistantSteps.map((s) =>
            s.kind === "text" ? { kind: "text", text: s.text } : { kind: "activity", actions: [...s.actions] }
          )
        : undefined;
    let assistantThinking = "";
    let assistantAttachments: MessageAttachment[] = [];
    let createdConversationId = "";
    let doneProvider: string | undefined;
    let doneModel: string | undefined;
    let doneTier: string | undefined;
    let revealAssistantAttachments = false;

    const upsertAssistantMessage = () => {
      const visibleAttachments = revealAssistantAttachments ? assistantAttachments : [];

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
                  thinking: assistantThinking || undefined,
                  attachments: visibleAttachments,
                  steps: cloneSteps(),
                  conversationId: createdConversationId || msg.conversationId,
                  provider: doneProvider ?? msg.provider,
                  model: doneModel ?? msg.model,
                  tier: doneTier ?? msg.tier,
                }
              : msg
          );
        }

        if (!assistantContent && !assistantThinking && visibleAttachments.length === 0 && assistantSteps.length === 0) {
          return normalized;
        }

        return [
          ...normalized,
          {
            id: assistantMessageId,
            conversationId: createdConversationId,
            role: "agent",
            content: assistantContent,
            thinking: assistantThinking || undefined,
            attachments: visibleAttachments,
            steps: cloneSteps(),
            createdAt: now,
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
        body: { content },
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
            if (typeof data.tool === "string" && data.tool) addActivityStep(data.tool);
            upsertAssistantMessage();
            return;
          }

          if (event === "token") {
            const text = typeof data.text === "string" ? data.text : "";
            if (!text) return;
            assistantContent += text;
            addTokenStep(text);
          } else if (event === "thinking") {
            const text = typeof data.text === "string" ? data.text : "";
            if (!text) return;
            assistantThinking += text;
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

      if (createdConversationId) {
        const finalMessages: Message[] = [
          { ...userMessage, conversationId: createdConversationId },
          {
            id: assistantMessageId,
            conversationId: createdConversationId,
            role: "agent",
            content: assistantContent,
            attachments: assistantAttachments.length > 0 ? assistantAttachments : undefined,
            steps: cloneSteps(),
            createdAt: now,
            provider: doneProvider,
            model: doneModel,
            tier: doneTier,
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
