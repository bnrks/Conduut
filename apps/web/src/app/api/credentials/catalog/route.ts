import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams.get("q") ?? "";
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  try {
    return await proxyAgentRequest(request, {
      method: "GET",
      path: `/api/credentials/catalog${suffix}`,
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
