"use client";

export interface ChatSendRequest {
  content: string;
  conversation_id?: string;
  provider?: string;
  model?: string;
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

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const parsed = parseSseEvent(rawEvent);
      if (parsed) onEvent(parsed);

      boundary = buffer.indexOf("\n\n");
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
