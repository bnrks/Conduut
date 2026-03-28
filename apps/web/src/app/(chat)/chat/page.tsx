"use client";

import { useState } from "react";
import { EmptyState } from "@/components/chat/empty-state";
import { ChatInput } from "@/components/chat/chat-input";

export default function NewChatPage() {
  const [inputValue, setInputValue] = useState("");

  const handleSend = (content: string) => {
    // In a real app this would create a conversation and redirect
    console.log("New conversation with:", content);
    setInputValue("");
  };

  const handlePromptClick = (prompt: string) => {
    setInputValue(prompt);
  };

  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden">
        <EmptyState onPromptClick={handlePromptClick} />
      </div>
      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSend={handleSend}
      />
    </>
  );
}
