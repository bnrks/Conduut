import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function getAgentBaseUrl(): string {
  return process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://localhost:8000";
}

export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("authorization");
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const query = new URL(request.url).search;
  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/usage${query}`, {
      headers: agentHeaders(request, { Authorization: authHeader }),
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}
