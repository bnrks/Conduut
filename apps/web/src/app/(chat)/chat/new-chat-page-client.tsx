"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";

import { ChatInput } from "@/components/chat/chat-input";
import {
  ClarificationPanel,
  type ClarificationPanelData,
} from "@/components/chat/clarification-panel";
import { EmptyState } from "@/components/chat/empty-state";
import { MessageList } from "@/components/chat/message-list";
import { ConnectionCallout } from "@/components/n8n/connection-callout";
import { useAuth } from "@/hooks/use-auth";
import { useN8nInstance } from "@/hooks/use-n8n-instance";
import { consumePendingExecutionRepair } from "@/lib/chat/pending-execution-repair";
import { setConversationCache } from "@/lib/chat/conversation-cache";
import {
  streamChat,
  type ChatIntent,
  type ExecutionReference,
  type UserInputResponse,
} from "@/lib/chat/sse";
import {
  assistantStreamFields,
  createAssistantStreamState,
  reduceAssistantStreamEvent,
} from "@/lib/chat/stream-state";
import { toolActivityLabel } from "@/lib/chat/tool-activity";
import type { ExecutionPolicy, Message } from "@/types/chat";

const AUTOMATION_SERVER_SETUP_INTENT: ChatIntent = "automation-server-setup";
const AUTOMATION_SERVER_SETUP_PROMPT =
  "Guide me through setting up a new customer-owned n8n automation server for Conduut. Give me one verified setup step at a time, wait for my output after each step, and never ask for passwords or SSH keys.";

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

function promptForIntent(intent?: string) {
  return intent === AUTOMATION_SERVER_SETUP_INTENT
    ? AUTOMATION_SERVER_SETUP_PROMPT
    : "";
}

function asChatIntent(intent?: string): ChatIntent | undefined {
  return intent === AUTOMATION_SERVER_SETUP_INTENT ? intent : undefined;
}

export interface NewChatPageClientProps {
  initialIntent?: string;
}

export function NewChatPageClient({
  initialIntent,
}: NewChatPageClientProps) {
  const router = useRouter();
  const { user } = useAuth();
  const { instance, error: instanceError, connectionRequired } = useN8nInstance();
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isAgentTyping, setIsAgentTyping] = useState(false);
  const [agentActivity, setAgentActivity] = useState<string | undefined>();
  const [agentActivities, setAgentActivities] = useState<string[]>([]);
  const [executionPolicy, setExecutionPolicy] = useState<ExecutionPolicy>("safe");
  const [executionPolicyLocked, setExecutionPolicyLocked] = useState(false);
  const didApplyIntentRef = useRef(false);
  const chatIntent = asChatIntent(initialIntent);
  const isAutomationServerSetupIntent = chatIntent === AUTOMATION_SERVER_SETUP_INTENT;
  const isFirstMessage = messages.length === 0;

  const handleSend = useCallback(async (
    content: string,
    executionReference?: ExecutionReference,
    userInputResponse?: UserInputResponse
  ) => {
    if (!user || isAgentTyping) return;

    const token = await user.getIdToken();
    const now = new Date().toISOString();
    const userMessage: Message = {
      id: createId("user"),
      conversationId: "",
      role: "user",
      content,
      createdAt: now,
      attachments: executionReference
        ? [
            {
              type: "execution_reference",
              data: {
                executionId: executionReference.execution_id,
                workflowName: executionReference.workflow_name,
                status: "error",
                intent: executionReference.intent,
              },
            },
          ]
        : undefined,
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
    setExecutionPolicyLocked(true);
    setAgentActivity(undefined);
    setAgentActivities([]);

    try {
      await streamChat({
        token,
        body: {
          content,
          intent: isFirstMessage ? chatIntent : undefined,
          execution_policy: executionPolicy,
          execution_reference: executionReference
            ? {
                execution_id: executionReference.execution_id,
                intent: executionReference.intent,
              }
            : undefined,
          user_input_response: userInputResponse,
        },
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
      if (!createdConversationId) {
        setExecutionPolicyLocked(false);
      }
      toast.error(error instanceof Error ? error.message : "Message could not be sent.");
    } finally {
      setIsAgentTyping(false);
      setAgentActivity(undefined);
      setAgentActivities([]);
    }
  }, [chatIntent, executionPolicy, isAgentTyping, isFirstMessage, router, user]);

  useEffect(() => {
    if (didApplyIntentRef.current) return;
    if (messages.length > 0 || isAgentTyping) return;
    const nextPrompt = promptForIntent(initialIntent);
    if (!nextPrompt || inputValue.trim().length > 0) return;
    didApplyIntentRef.current = true;
    setInputValue(nextPrompt);
  }, [initialIntent, inputValue, isAgentTyping, messages.length]);

  useEffect(() => {
    if (isAutomationServerSetupIntent) return;
    if (!user || isAgentTyping || messages.length > 0) return;
    const reference = consumePendingExecutionRepair();
    if (!reference) return;
    void handleSend("Bu başarısız çalıştırmayı incele ve düzelt.", reference);
  }, [handleSend, isAgentTyping, isAutomationServerSetupIntent, messages.length, user]);

  const handlePromptClick = (prompt: string) => {
    setInputValue(prompt);
  };
  const clarification = activeClarification(messages, isAgentTyping);

  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden">
        {messages.length === 0 ? (
          <div className="flex flex-1 flex-col gap-4">
            {isAutomationServerSetupIntent ? (
              <div className="px-4 pt-4">
                <div className="mx-auto max-w-3xl rounded-xl border border-conduut-500/20 bg-conduut-500/[0.04] px-4 py-3">
                  <p className="text-[13px] font-medium text-foreground">
                    Guided automation server setup
                  </p>
                  <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                    Conduut will help you prepare a new n8n server one verified step at a
                    time. Run commands on your VPS yourself and paste back the
                    output.
                  </p>
                </div>
              </div>
            ) : connectionRequired ? (
              <div className="px-4 pt-4">
                <div className="mx-auto max-w-3xl">
                  <ConnectionCallout
                    compact
                    statusLabel={instance?.connectionStatus ? instance.connectionStatus.replaceAll("_", " ") : undefined}
                    description={
                      instanceError ??
                      "Connect your own n8n server before asking Conduut to build or inspect automations."
                    }
                  />
                </div>
              </div>
            ) : null}
            <EmptyState onPromptClick={handlePromptClick} />
          </div>
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
        {!clarification &&
        connectionRequired &&
        messages.length > 0 &&
        !isAutomationServerSetupIntent ? (
          <div className="px-4 pb-3">
            <div className="mx-auto max-w-3xl">
              <ConnectionCallout
                compact
                statusLabel={instance?.connectionStatus ? instance.connectionStatus.replaceAll("_", " ") : undefined}
                description={
                  instanceError ??
                  "Connect your automation server in Settings so Conduut can work against your n8n instance."
                }
              />
            </div>
          </div>
        ) : null}
        {clarification ? (
          <div className="px-4 pb-4">
            <div className="mx-auto max-w-3xl">
              <ClarificationPanel
                key={clarification.messageId}
                data={clarification.data}
                onSubmit={(payload) => {
                  void handleSend(payload.content, undefined, payload.structuredResponse);
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
            executionPolicy={executionPolicy}
            executionPolicyLocked={executionPolicyLocked}
            onExecutionPolicyChange={setExecutionPolicy}
          />
        )}
      </div>
    </>
  );
}
