import { NextRequest, NextResponse } from "next/server";

import {
  fetchAgentResponse,
  isAgentTimeoutError,
  releaseAgentResponse,
} from "@/lib/agent-client";

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
    const response = await fetchAgentResponse(request, {
      auth: "none",
      body: JSON.stringify({ code, state }),
      contentType: "application/json",
      method: "POST",
      path: "/api/connections/google/callback",
      timeoutMs: 30_000,
    });

    if (response instanceof NextResponse) {
      return redirectWithQuery(request, "/dashboard/connections", {
        error: "Google connection could not be completed.",
      });
    }

    try {
      if (!response.ok) {
        return redirectWithQuery(request, "/dashboard/connections", {
          error: await getErrorMessage(
            response,
            "Google connection could not be completed."
          ),
        });
      }

      const payload = (await response.json().catch(() => null)) as {
        connection?: { id?: string };
        returnTo?: string;
      } | null;
      return redirectWithQuery(request, safeReturnTo(payload?.returnTo), {
        connected: payload?.connection?.id ?? "google",
      });
    } finally {
      releaseAgentResponse(response);
    }
  } catch (error) {
    if (isAgentTimeoutError(error)) {
      return redirectWithQuery(request, "/dashboard/connections", {
        error: "Agent service timed out before responding.",
      });
    }
    return redirectWithQuery(request, "/dashboard/connections", {
      error: "Agent service is unreachable.",
    });
  }
}
