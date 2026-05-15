import { NextRequest, NextResponse } from "next/server";

const SUPPORTED_SERVICES = new Set(["gmail", "sheets"]);

function getAgentBaseUrl(): string {
  const fromEnv =
    process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

function getService(request: NextRequest, body: Record<string, unknown>): string {
  const fromQuery = request.nextUrl.searchParams.get("service");
  const fromBody = typeof body.service === "string" ? body.service : null;
  const service = fromQuery || fromBody || "gmail";
  return SUPPORTED_SERVICES.has(service) ? service : "gmail";
}

async function toResponsePayload(response: Response) {
  const data = await response.json().catch(() => null);
  return NextResponse.json(data, { status: response.status });
}

export async function POST(request: NextRequest) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json(
      { message: "Missing Authorization header" },
      { status: 401 }
    );
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const service = getService(request, body);
  const agentBody = { ...body };
  delete agentBody.service;

  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/connections/google/${service}/authorize`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: authHeader,
        },
        body: JSON.stringify(agentBody),
        cache: "no-store",
      }
    );
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json(
      { message: "Agent service is unreachable." },
      { status: 503 }
    );
  }
}
