import { NextRequest, NextResponse } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ workflowId: string }> }
) {
  const { workflowId } = await context.params;
  const url = new URL(request.url);
  const action = url.searchParams.get("action") ?? "activate";

  try {
    return await proxyAgentRequest(request, {
      method: "PATCH",
      path: `/api/workflows/${encodeURIComponent(workflowId)}/${action}`,
      responseType: "json",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ workflowId: string }> }
) {
  const { workflowId } = await context.params;
  try {
    return await proxyAgentRequest(request, {
      method: "DELETE",
      path: `/api/workflows/${encodeURIComponent(workflowId)}`,
      responseType: "json",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ workflowId: string }> }
) {
  const { workflowId } = await context.params;
  const url = new URL(request.url);
  const action = url.searchParams.get("action") ?? "run";
  if (!["run", "preview-run", "batch-preview", "batch-run", "batch-run-stream"].includes(action)) {
    return NextResponse.json({ message: "Unsupported workflow action" }, { status: 400 });
  }

  try {
    const body = await request.json().catch(() => ({ input: {}, source: "dashboard" }));
    const agentAction =
      action === "batch-run-stream"
          ? "batch-run/stream"
          : action === "batch-preview"
            ? "batch-preview"
            : action === "batch-run"
              ? "batch-run"
              : action === "preview-run"
                ? "preview-run"
                : "run";
    if (action === "batch-run-stream") {
      return await proxyAgentRequest(request, {
        body: JSON.stringify(body),
        contentType: "application/json",
        method: "POST",
        path: `/api/workflows/${encodeURIComponent(workflowId)}/${agentAction}`,
        responseType: "stream",
      });
    }
    return await proxyAgentRequest(request, {
      body: JSON.stringify(body),
      contentType: "application/json",
      method: "POST",
      path: `/api/workflows/${encodeURIComponent(workflowId)}/${agentAction}`,
      responseType: "json",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
