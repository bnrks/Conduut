import { NextRequest, NextResponse } from "next/server";

const agent = () =>
  process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://localhost:8000";

async function proxy(req: NextRequest, path: string, method: string, body?: unknown) {
  const auth = req.headers.get("authorization");
  if (!auth) return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  try {
    const res = await fetch(`${agent()}${path}`, {
      method,
      headers: { Authorization: auth, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    return NextResponse.json(await res.json().catch(() => null), { status: res.status });
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}

export const GET = (req: NextRequest) => proxy(req, "/api/settings/favorites", "GET");
