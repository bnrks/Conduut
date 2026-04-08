import { NextRequest, NextResponse } from "next/server";

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

  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/chat/send`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: authHeader,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    if (!response.body) {
      const payload = await response.json().catch(() => null);
      return NextResponse.json(payload, { status: response.status });
    }

    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Conversation-Id": response.headers.get("x-conversation-id") || "",
      },
    });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable. Please check backend URL/config." }, { status: 503 });
  }
}
