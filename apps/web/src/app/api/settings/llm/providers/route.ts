import { NextRequest, NextResponse } from "next/server";

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

export async function GET(request: NextRequest) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/settings/llm/providers`, {
      method: "GET",
      headers: {
        Authorization: authHeader,
      },
      cache: "no-store",
    });
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable. Please check backend URL/config." }, { status: 503 });
  }
}

export async function PUT(request: NextRequest) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const body = await request.json();
  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/settings/llm/providers`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: authHeader,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable. Please check backend URL/config." }, { status: 503 });
  }
}
