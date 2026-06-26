import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

function getAgentBaseUrl(): string {
  const fromEnv = process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

export async function GET(request: NextRequest) {
  const path = request.nextUrl.searchParams.get("path") ?? "";
  if (!path) {
    return new NextResponse(null, { status: 400 });
  }
  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/credentials/icon?path=${encodeURIComponent(path)}`,
      { method: "GET", headers: agentHeaders(request, {}), cache: "no-store" }
    );
    if (!response.ok) {
      return new NextResponse(null, { status: response.status });
    }
    const body = await response.arrayBuffer();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "image/svg+xml",
        "Cache-Control": "public, max-age=86400",
      },
    });
  } catch {
    return new NextResponse(null, { status: 502 });
  }
}
