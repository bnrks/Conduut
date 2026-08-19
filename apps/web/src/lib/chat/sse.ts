"use client";

import type { ExecutionPolicy } from "@/types/chat";

export interface ExecutionReference {
  execution_id: string;
  intent: "diagnose_and_fix";
  workflow_name?: string;
}

export interface UserInputResponse {
  request_id: string;
  request_kind: "workflow_run_approval";
  workflow_id: string;
  decision: "approve" | "cancel";
}

export type ChatIntent = "automation-server-setup";

export interface ChatSendRequest {
  content: string;
  conversation_id?: string;
  intent?: ChatIntent;
  execution_policy?: ExecutionPolicy;
  execution_reference?: ExecutionReference;
  user_input_response?: UserInputResponse;
}

export interface ChatStreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export async function streamChat({
  token,
  body,
  onEvent,
}: {
  token: string;
  body: ChatSendRequest;
  onEvent: (event: ChatStreamEvent) => void;
}): Promise<void> {
  const response = await fetch("/api/chat/send", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let message = "Mesaj gonderilemedi.";
    const payload = (await response.json().catch(() => null)) as { detail?: { message?: string } | string; message?: string } | null;
    if (typeof payload?.detail === "string") message = payload.detail;
    else if (typeof payload?.detail?.message === "string") message = payload.detail.message;
    else if (typeof payload?.message === "string") message = payload.message;
    throw new Error(message);
  }

  if (!response.body) {
    throw new Error("Stream body alinamadi.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushEvents = () => {
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseEvent(rawEvent);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      flushEvents();
    }
    // Flush any remaining content after the stream ends
    buffer += decoder.decode();
    if (buffer.trim().length > 0) {
      // Handle a final event that wasn't terminated with \n\n
      const parsed = parseSseEvent(buffer);
      if (parsed) onEvent(parsed);
      buffer = "";
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* noop */
    }
  }
}

function parseSseEvent(raw: string): ChatStreamEvent | null {
  const lines = raw.replaceAll("\r", "").split("\n");
  let event = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      data += line.slice(5).trimStart();
    }
  }

  if (!data) return null;

  try {
    return { event, data: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return null;
  }
}
