import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ conversationId: string }> }
) {
  const { conversationId } = await context.params;
  try {
    return await proxyAgentRequest(request, {
      method: "GET",
      path: `/api/conversations/${encodeURIComponent(conversationId)}`,
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
  context: { params: Promise<{ conversationId: string }> }
) {
  const { conversationId } = await context.params;
  try {
    return await proxyAgentRequest(request, {
      method: "DELETE",
      path: `/api/conversations/${encodeURIComponent(conversationId)}`,
      responseType: "json",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
