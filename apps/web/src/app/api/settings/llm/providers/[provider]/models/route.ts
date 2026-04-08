import { NextRequest, NextResponse } from "next/server";

function getAgentBaseUrl(): string {
  return process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://localhost:8000";
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ provider: string }> }
) {
  const authHeader = request.headers.get("authorization");
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const { provider } = await params;
  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/settings/llm/providers/${encodeURIComponent(provider)}/models`,
      {
        method: "GET",
        headers: { Authorization: authHeader },
        cache: "no-store",
      }
    );
    const data = await response.json().catch(() => null);
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}
