import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function GET(request: NextRequest) {
  try {
    return await proxyAgentRequest(request, {
      method: "GET",
      path: "/api/credentials",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  try {
    return await proxyAgentRequest(request, {
      body: JSON.stringify(body),
      contentType: "application/json",
      method: "POST",
      path: "/api/credentials",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
