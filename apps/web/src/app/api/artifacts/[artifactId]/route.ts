import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ artifactId: string }> }
) {
  const { artifactId } = await context.params;
  try {
    return await proxyAgentRequest(request, {
      method: "DELETE",
      path: `/api/artifacts/${encodeURIComponent(artifactId)}`,
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
