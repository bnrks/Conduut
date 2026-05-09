import { NextRequest, NextResponse } from "next/server";

function getAgentBaseUrl(): string {
  const fromEnv =
    process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function safeReturnTo(value: unknown): string {
  if (typeof value !== "string") return "/dashboard/connections";
  if (!value.startsWith("/") || value.startsWith("//")) {
    return "/dashboard/connections";
  }
  return value;
}

function redirectWithQuery(
  request: NextRequest,
  pathname: string,
  params: Record<string, string>
) {
  const url = new URL(pathname, request.url);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return NextResponse.redirect(url);
}

async function getErrorMessage(
  response: Response,
  fallback: string
): Promise<string> {
  const payload = (await response.json().catch(() => null)) as {
    detail?: { message?: string } | string;
    message?: string;
  } | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  if (typeof payload?.message === "string") return payload.message;
  return fallback;
}

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const error = searchParams.get("error");
  const code = searchParams.get("code");
  const state = searchParams.get("state");

  if (error) {
    return redirectWithQuery(request, "/dashboard/connections", { error });
  }

  if (!code || !state) {
    return redirectWithQuery(request, "/dashboard/connections", {
      error: "Google OAuth callback is missing code or state.",
    });
  }

  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/connections/google/gmail/callback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, state }),
        cache: "no-store",
      }
    );

    if (!response.ok) {
      return redirectWithQuery(request, "/dashboard/connections", {
        error: await getErrorMessage(
          response,
          "Google Gmail connection could not be completed."
        ),
      });
    }

    const payload = (await response.json().catch(() => null)) as {
      returnTo?: string;
    } | null;
    return redirectWithQuery(request, safeReturnTo(payload?.returnTo), {
      connected: "google",
    });
  } catch {
    return redirectWithQuery(request, "/dashboard/connections", {
      error: "Agent service is unreachable.",
    });
  }
}
