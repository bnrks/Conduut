import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

const agent = () =>
  process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://localhost:8000";

type Ctx = { params: Promise<{ provider: string; model: string }> };

async function proxy(req: NextRequest, method: string, provider: string, model: string) {
  const auth = req.headers.get("authorization");
  if (!auth) return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  try {
    const res = await fetch(
      `${agent()}/api/settings/favorites/${encodeURIComponent(provider)}/${encodeURIComponent(model)}`,
      { method, headers: agentHeaders(req, { Authorization: auth }), cache: "no-store" }
    );
    return NextResponse.json(await res.json().catch(() => null), { status: res.status });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}

export async function POST(req: NextRequest, { params }: Ctx) {
  const { provider, model } = await params;
  return proxy(req, "POST", provider, model);
}

export async function DELETE(req: NextRequest, { params }: Ctx) {
  const { provider, model } = await params;
  return proxy(req, "DELETE", provider, model);
}
