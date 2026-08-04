import { NextRequest } from "next/server";

import { proxyJsonRequest } from "@/app/api/n8n/_utils";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  return proxyJsonRequest(request, "/api/n8n/migration");
}
