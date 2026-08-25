import { NextRequest } from "next/server";

import { proxyJsonRequest } from "@/app/api/n8n/_utils";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ executionId: string }> }
) {
  const { executionId } = await context.params;
  return proxyJsonRequest(
    request,
    `/api/executions/${encodeURIComponent(executionId)}`
  );
}
