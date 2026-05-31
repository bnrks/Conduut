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
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const data = await response.json().catch(() => null);
  return NextResponse.json(data, { status: response.status });
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ workflowId: string }> }
) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const { workflowId } = await context.params;
  const url = new URL(request.url);
  const action = url.searchParams.get("action") ?? "activate";

  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/workflows/${encodeURIComponent(workflowId)}/${action}`,
      {
        method: "PATCH",
        headers: agentHeaders(request, { Authorization: authHeader }),
        cache: "no-store",
      }
    );
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ workflowId: string }> }
) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const { workflowId } = await context.params;
  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/workflows/${encodeURIComponent(workflowId)}`,
      {
        method: "DELETE",
        headers: agentHeaders(request, { Authorization: authHeader }),
        cache: "no-store",
      }
    );
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ workflowId: string }> }
) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const { workflowId } = await context.params;
  const url = new URL(request.url);
  const action = url.searchParams.get("action") ?? "run";
  if (!["run", "batch-run"].includes(action)) {
    return NextResponse.json({ message: "Unsupported workflow action" }, { status: 400 });
  }

  try {
    const body = await request.json().catch(() => ({ input: {}, source: "dashboard" }));
    const agentAction = action === "batch-run" ? "batch-run" : "run";
    const response = await fetch(
      `${getAgentBaseUrl()}/api/workflows/${encodeURIComponent(workflowId)}/${agentAction}`,
      {
        method: "POST",
        headers: agentHeaders(request, {
          Authorization: authHeader,
          "Content-Type": "application/json",
        }),
        body: JSON.stringify(body),
        cache: "no-store",
      }
    );
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}
