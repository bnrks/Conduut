import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

const DEFAULT_AGENT_BASE_URL = "http://localhost:8000";
const DEFAULT_JSON_TIMEOUT_MS = 30_000;
const DEFAULT_STREAM_TIMEOUT_MS = 905_000;
const METADATA_TIMEOUT_MS = 5_000;
const GOOGLE_METADATA_IDENTITY_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

type ProxyInit = {
  auth?: "firebase" | "none";
  body?: BodyInit | null;
  contentType?: string;
  method?: string;
  path: string;
  responseType?: "json" | "stream" | "binary";
  streamHeaders?: Record<string, string>;
  timeoutMs?: number;
};

type BinaryProxyResult = {
  body: ArrayBuffer;
  contentType: string;
  status: number;
};

type UpstreamFetchInit = Omit<ProxyInit, "streamHeaders">;

let cachedServerlessToken:
  | {
      audience: string;
      expiresAt: number;
      token: string;
    }
  | undefined;

const responseCleanup = new WeakMap<Response, () => void>();

export function releaseAgentResponse(response: Response): void {
  const cleanup = responseCleanup.get(response);
  if (!cleanup) return;
  responseCleanup.delete(response);
  cleanup();
}

export function getAgentBaseUrl(): string {
  const serverOnlyBaseUrl = String(process.env.AGENT_API_BASE_URL || "").trim();
  if (shouldUsePrivateAgentAuth() && !serverOnlyBaseUrl) {
    throw new Error(
      "AGENT_API_BASE_URL must be set when AGENT_API_AUTH_MODE=cloud_run."
    );
  }
  return (serverOnlyBaseUrl || DEFAULT_AGENT_BASE_URL).replace(/\/+$/, "");
}

export function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

export function missingAuthorizationResponse() {
  return NextResponse.json(
    { message: "Missing Authorization header" },
    { status: 401 }
  );
}

export async function toJsonResponse(response: Response) {
  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  let data: unknown = null;
  try {
    data = await response.json();
  } catch (error) {
    if (isAgentTimeoutError(error)) throw error;
  }
  return NextResponse.json(data, { status: response.status });
}

export function isAgentTimeoutError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function agentUnavailableResponse() {
  return NextResponse.json(
    {
      message:
        "Agent service is unreachable. Please check backend URL/config.",
    },
    { status: 503 }
  );
}

export function agentTimeoutResponse() {
  return NextResponse.json(
    {
      message:
        "Agent service timed out before responding. Please retry or check backend health.",
    },
    { status: 504 }
  );
}

function shouldUsePrivateAgentAuth(): boolean {
  return (
    String(process.env.AGENT_API_AUTH_MODE || "").trim().toLowerCase() ===
    "cloud_run"
  );
}

function getPrivateAgentAudience(): string | null {
  const audience = String(process.env.AGENT_API_AUDIENCE || "").trim();
  return audience ? audience : null;
}

function getJsonTimeoutMs(): number {
  const parsed = Number(process.env.AGENT_API_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : DEFAULT_JSON_TIMEOUT_MS;
}

function getStreamTimeoutMs(): number {
  const parsed = Number(process.env.AGENT_API_STREAM_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : DEFAULT_STREAM_TIMEOUT_MS;
}

function getTimeoutMs(
  responseType: ProxyInit["responseType"],
  override?: number
): number {
  if (override && override > 0) {
    return override;
  }
  return responseType === "stream" ? getStreamTimeoutMs() : getJsonTimeoutMs();
}

async function getServerlessAuthorizationHeader(): Promise<string | null> {
  if (!shouldUsePrivateAgentAuth()) {
    return null;
  }

  const audience = getPrivateAgentAudience();
  if (!audience) {
    throw new Error(
      "AGENT_API_AUDIENCE must be set when AGENT_API_AUTH_MODE=cloud_run."
    );
  }

  const now = Date.now();
  if (
    cachedServerlessToken &&
    cachedServerlessToken.audience === audience &&
    cachedServerlessToken.expiresAt > now
  ) {
    return `Bearer ${cachedServerlessToken.token}`;
  }

  const tokenUrl = new URL(GOOGLE_METADATA_IDENTITY_URL);
  tokenUrl.searchParams.set("audience", audience);
  tokenUrl.searchParams.set("format", "full");

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), METADATA_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(tokenUrl, {
      headers: { "Metadata-Flavor": "Google" },
      cache: "no-store",
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    throw new Error(
      `Could not mint Cloud Run identity token (${response.status}).`
    );
  }

  const token = (await response.text()).trim();
  if (!token) {
    throw new Error("Cloud Run identity token was empty.");
  }

  cachedServerlessToken = {
    audience,
    expiresAt: now + 50 * 60 * 1000,
    token,
  };
  return `Bearer ${token}`;
}

async function buildUpstreamHeaders(
  request: NextRequest,
  auth: ProxyInit["auth"],
  contentType?: string
): Promise<Headers | NextResponse> {
  const headers = agentHeaders(request, {});

  if (auth !== "none") {
    const authHeader = getAuthHeader(request);
    if (!authHeader) {
      return missingAuthorizationResponse();
    }
    headers.set("Authorization", authHeader);
  }

  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  const serverlessAuth = await getServerlessAuthorizationHeader();
  if (serverlessAuth) {
    headers.set("X-Serverless-Authorization", serverlessAuth);
  }

  return headers;
}

function streamUpstreamBody(
  upstream: Response,
  extraHeaders?: Record<string, string>
): Response {
  const reader = upstream.body!.getReader();
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) {
          releaseAgentResponse(upstream);
          controller.close();
          return;
        }
        if (value) {
          controller.enqueue(value);
        }
      } catch (error) {
        releaseAgentResponse(upstream);
        controller.error(error);
      }
    },
    cancel() {
      releaseAgentResponse(upstream);
      void reader.cancel();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      "X-Conversation-Id":
        upstream.headers.get("x-conversation-id") || "",
      ...(extraHeaders ?? {}),
    },
  });
}

export async function fetchAgentResponse(
  request: NextRequest,
  init: UpstreamFetchInit
): Promise<Response | NextResponse> {
  const headers = await buildUpstreamHeaders(
    request,
    init.auth ?? "firebase",
    init.contentType
  );
  if (headers instanceof NextResponse) {
    return headers;
  }

  const timeoutMs = getTimeoutMs(init.responseType, init.timeoutMs);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${getAgentBaseUrl()}${init.path}`, {
      method: init.method ?? "GET",
      headers,
      body: init.body,
      cache: "no-store",
      signal: controller.signal,
    });
    responseCleanup.set(response, () => clearTimeout(timer));
    return response;
  } catch (error) {
    clearTimeout(timer);
    throw error;
  }
}

export async function proxyAgentRequest(
  request: NextRequest,
  init: ProxyInit & { responseType: "binary" }
): Promise<NextResponse | BinaryProxyResult>;
export async function proxyAgentRequest(
  request: NextRequest,
  init: ProxyInit
): Promise<Response | NextResponse>;
export async function proxyAgentRequest(
  request: NextRequest,
  init: ProxyInit
): Promise<Response | NextResponse | BinaryProxyResult> {
  const response = await fetchAgentResponse(request, init);
  if (response instanceof NextResponse) {
    return response;
  }

  if (init.responseType === "stream") {
    if (!response.ok || !response.body) {
      try {
        return await toJsonResponse(response);
      } finally {
        releaseAgentResponse(response);
      }
    }
    return streamUpstreamBody(response, init.streamHeaders);
  }

  try {
    if (init.responseType === "binary") {
      if (!response.ok) {
        return new NextResponse(null, { status: response.status });
      }

      return {
        body: await response.arrayBuffer(),
        contentType:
          response.headers.get("content-type") ?? "application/octet-stream",
        status: response.status,
      };
    }

    return await toJsonResponse(response);
  } finally {
    releaseAgentResponse(response);
  }
}
