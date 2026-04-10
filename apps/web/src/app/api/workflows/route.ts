import { NextRequest, NextResponse } from "next/server";

function getAgentBaseUrl(): string {
  const fromEnv = process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

export async function GET(request: NextRequest) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/workflows`, {
      method: "GET",
      headers: {
        Authorization: authHeader,
      },
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable. Please check backend URL/config." }, { status: 503 });
  }
}
