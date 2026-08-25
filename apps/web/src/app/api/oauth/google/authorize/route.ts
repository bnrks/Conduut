import { NextRequest } from "next/server";

import {
  agentTimeoutResponse,
  agentUnavailableResponse,
  isAgentTimeoutError,
  proxyAgentRequest,
} from "@/lib/agent-client";

const SUPPORTED_SERVICES = new Set(["gmail", "sheets"]);

function getService(request: NextRequest, body: Record<string, unknown>): string {
  const fromQuery = request.nextUrl.searchParams.get("service");
  const fromBody = typeof body.service === "string" ? body.service : null;
  const service = fromQuery || fromBody || "gmail";
  return SUPPORTED_SERVICES.has(service) ? service : "gmail";
}

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const service = getService(request, body);
  const agentBody = { ...body };
  delete agentBody.service;
  const permissionPack = request.nextUrl.searchParams.get("permission_pack");
  if (permissionPack && typeof agentBody.permission_pack !== "string") {
    agentBody.permission_pack = permissionPack;
  }
  const requestedCapability = request.nextUrl.searchParams.getAll(
    "requested_capabilities"
  );
  if (requestedCapability.length && !Array.isArray(agentBody.requested_capabilities)) {
    agentBody.requested_capabilities = requestedCapability;
  }

  try {
    return await proxyAgentRequest(request, {
      body: JSON.stringify(agentBody),
      contentType: "application/json",
      method: "POST",
      path: `/api/connections/google/${service}/authorize`,
    });
  } catch (error) {
    return isAgentTimeoutError(error)
      ? agentTimeoutResponse()
      : agentUnavailableResponse();
  }
}
