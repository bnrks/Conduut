import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ credentialId: string }> }
) {
  const { credentialId } = await context.params;
  const body = await request.json();
  try {
    return await proxyAgentRequest(request, {
      body: JSON.stringify(body),
      contentType: "application/json",
      method: "POST",
      path: `/api/credentials/${encodeURIComponent(credentialId)}/finalize`,
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
