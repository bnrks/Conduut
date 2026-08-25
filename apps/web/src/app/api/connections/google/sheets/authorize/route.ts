import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  try {
    return await proxyAgentRequest(request, {
      body: JSON.stringify(body),
      contentType: "application/json",
      method: "POST",
      path: "/api/connections/google/sheets/authorize",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
