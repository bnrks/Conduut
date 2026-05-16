import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function getAgentBaseUrl(): string {
  const fromEnv = process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

export async function POST(request: NextRequest) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const body = await request.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${getAgentBaseUrl()}/api/chat/send`, {
      method: "POST",
      headers: agentHeaders(request, {
        "Content-Type": "application/json",
        Authorization: authHeader,
      }),
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable. Please check backend URL/config." }, { status: 503 });
  }

  if (!upstream.ok || !upstream.body) {
    const payload = await upstream.json().catch(() => null);
    return NextResponse.json(payload, { status: upstream.status });
  }

  // Manually pump the upstream stream to disable Node.js buffering.
  // Using a fresh ReadableStream forces Next.js to pipe chunks to the client
  // as they arrive, instead of waiting for the entire upstream body.
  const reader = upstream.body.getReader();
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) {
          controller.close();
          return;
        }
        if (value) controller.enqueue(value);
      } catch (err) {
        controller.error(err);
      }
    },
    cancel() {
      void reader.cancel();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
      "X-Conversation-Id": upstream.headers.get("x-conversation-id") || "",
    },
  });
}
