import { NextRequest } from "next/server";

import { proxyJsonRequest } from "@/app/api/n8n/_utils";

export async function GET(request: NextRequest) {
  return proxyJsonRequest(request, "/api/workflows");
}
