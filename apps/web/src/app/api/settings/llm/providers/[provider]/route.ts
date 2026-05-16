import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

function getAgentBaseUrl(): string {
  const fromEnv = process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

async function toResponsePayload(response: Response) {
  const data = await response.json().catch(() => null);
  return NextResponse.json(data, { status: response.status });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ provider: string }> }
) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const { provider } = await params;
  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/settings/llm/providers/${encodeURIComponent(provider)}`, {
      method: "DELETE",
      headers: agentHeaders(request, {
        Authorization: authHeader,
      }),
      cache: "no-store",
    });
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable. Please check backend URL/config." }, { status: 503 });
  }
}
