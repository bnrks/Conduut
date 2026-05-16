import type { NextRequest } from "next/server";

export function requestId(request: NextRequest): string {
  return request.headers.get("x-request-id") || crypto.randomUUID();
}

export function agentHeaders(
  request: NextRequest,
  headers: Record<string, string> = {}
): Headers {
  const result = new Headers(headers);
  result.set("X-Request-ID", requestId(request));
  return result;
}
