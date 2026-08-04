import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

export function getAgentBaseUrl(): string {
  return process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://localhost:8000";
}

export function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

export async function toJsonResponse(response: Response) {
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data = await response.json().catch(() => null);
  return NextResponse.json(data, { status: response.status });
}

export async function proxyJsonRequest(
  request: NextRequest,
  path: string,
  init?: {
    method?: string;
    body?: unknown;
  }
) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  try {
    const response = await fetch(`${getAgentBaseUrl()}${path}`, {
      method: init?.method ?? "GET",
      headers: agentHeaders(request, {
        Authorization: authHeader,
        ...(init?.body !== undefined ? { "Content-Type": "application/json" } : {}),
      }),
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
    return await toJsonResponse(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}
