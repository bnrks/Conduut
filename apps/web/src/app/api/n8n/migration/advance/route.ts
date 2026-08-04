import { NextRequest } from "next/server";

import { proxyJsonRequest } from "@/app/api/n8n/_utils";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  return proxyJsonRequest(request, "/api/n8n/migration/advance", { method: "POST", body });
}
