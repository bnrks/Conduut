"use client";

import { useState } from "react";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { EmptyState } from "@/components/chat/empty-state";
import { useChatStore } from "@/lib/stores/chat-store";
import type { Message } from "@/types/chat";

// Realistic mock conversation
const MOCK_MESSAGES: Message[] = [
  {
    id: "msg-1",
    conversationId: "conv-1",
    role: "user",
    content:
      "I want to get Slack notifications when someone stars my GitHub repo",
    createdAt: new Date(Date.now() - 1000 * 60 * 8).toISOString(),
  },
  {
    id: "msg-2",
    conversationId: "conv-1",
    role: "agent",
    content:
      "I'll create that workflow for you! Let me set up a GitHub trigger connected to Slack.\n\nThis workflow will:\n• Watch for new stars on your GitHub repository\n• Send a formatted message to your chosen Slack channel\n• Include the stargazer's username and a link to your repo",
    createdAt: new Date(Date.now() - 1000 * 60 * 7).toISOString(),
    attachments: [
      {
        type: "workflow_preview",
        data: {
          name: "GitHub Stars → Slack Notification",
          nodeCount: 3,
          status: "inactive",
          id: "wf-001",
        },
      },
    ],
  },
  {
    id: "msg-3",
    conversationId: "conv-1",
    role: "agent",
    content:
      "To proceed, I need to connect your GitHub account so I can access your repositories.",
    createdAt: new Date(Date.now() - 1000 * 60 * 6).toISOString(),
    attachments: [
      {
        type: "oauth_prompt",
        data: {
          service: "GitHub",
          description: "Required to listen for star events on your repositories",
        },
      },
    ],
  },
  {
    id: "msg-4",
    conversationId: "conv-1",
    role: "user",
    content: "Sure, connect it",
    createdAt: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
  },
  {
    id: "msg-5",
    conversationId: "conv-1",
    role: "agent",
    content:
      "GitHub is now connected! Your workflow is active.\n\nYou'll get a Slack message whenever someone stars your repo. The notification will look like this:\n\n⭐ **@username** just starred **your-repo**\n\nWould you like to customize the Slack channel or the message format?",
    createdAt: new Date(Date.now() - 1000 * 60 * 2).toISOString(),
    attachments: [
      {
        type: "workflow_preview",
        data: {
          name: "GitHub Stars → Slack Notification",
          nodeCount: 3,
          status: "active",
          id: "wf-001",
        },
      },
    ],
  },
];

export default function ConversationPage() {
  const [messages, setMessages] = useState<Message[]>(MOCK_MESSAGES);
  const [inputValue, setInputValue] = useState("");
  const { isAgentTyping } = useChatStore();

  const handleSend = (content: string) => {
    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      conversationId: "conv-1",
      role: "user",
      content,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
  };

  const handlePromptClick = (prompt: string) => {
    setInputValue(prompt);
  };

  return (
    <>
      {messages.length === 0 ? (
        <EmptyState onPromptClick={handlePromptClick} />
      ) : (
        <MessageList messages={messages} isAgentTyping={isAgentTyping} />
      )}
      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSend={handleSend}
        isAgentTyping={isAgentTyping}
      />
    </>
  );
}
