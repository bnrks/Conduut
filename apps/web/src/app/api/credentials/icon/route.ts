import { NextRequest, NextResponse } from "next/server";

import {
  agentUnavailableResponse,
  proxyAgentRequest,
} from "@/lib/agent-client";

export async function GET(request: NextRequest) {
  const path = request.nextUrl.searchParams.get("path") ?? "";
  if (!path) {
    return new NextResponse(null, { status: 400 });
  }
  try {
    const response = await proxyAgentRequest(request, {
      auth: "none",
      method: "GET",
      path: `/api/credentials/icon?path=${encodeURIComponent(path)}`,
      responseType: "binary",
    });
    if (response instanceof NextResponse) {
      return response;
    }
    return new NextResponse(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.contentType || "image/svg+xml",
        "Cache-Control": "public, max-age=86400",
      },
    });
  } catch {
    return agentUnavailableResponse();
  }
}
