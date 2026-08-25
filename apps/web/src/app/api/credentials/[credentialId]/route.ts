import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ credentialId: string }> }
) {
  const { credentialId } = await context.params;
  try {
    return await proxyAgentRequest(request, {
      method: "DELETE",
      path: `/api/credentials/${encodeURIComponent(credentialId)}`,
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
