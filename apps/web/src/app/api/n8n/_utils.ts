import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function proxyJsonRequest(
  request: NextRequest,
  path: string,
  init?: {
    method?: string;
    body?: unknown;
    auth?: "firebase" | "none";
  }
) {
  try {
    return await proxyAgentRequest(request, {
      auth: init?.auth,
      body:
        init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      contentType:
        init?.body !== undefined ? "application/json" : undefined,
      method: init?.method,
      path,
      responseType: "json",
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
