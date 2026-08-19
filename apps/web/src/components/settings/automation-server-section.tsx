"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  FileText,
  RefreshCw,
  Server,
  ShieldAlert,
  TerminalSquare,
} from "lucide-react";
import { toast } from "sonner";

import { ConnectionCallout } from "@/components/n8n/connection-callout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { useN8nInstance } from "@/hooks/use-n8n-instance";
import { cn } from "@/lib/utils";
import type {
  N8nInstanceCheckResult,
  N8nSetupGuidePayload,
  N8nSetupGuideStage,
} from "@/types/n8n";
import { isN8nConnected, isN8nConnectionIssue } from "@/types/n8n";

const CANONICAL_N8N_VERSION = "1.121.3";

const AUTOMATION_SERVER_EXPECTATIONS = [
  {
    title: "Public HTTPS endpoint",
    description: "Use an n8n URL that Conduut can reach server-to-server without VPN, localhost, or private networking.",
  },
  {
    title: "Admin-created API key",
    description: "Create a fresh API key in your own n8n admin account and paste it here once for verification and storage.",
  },
  {
    title: "Supported canonical version",
    description: `Conduut currently checks for n8n ${CANONICAL_N8N_VERSION} and fails closed when the detected version is outside the supported contract.`,
  },
  {
    title: "Correct public webhook origin",
    description: "Your n8n base URL and webhook setup must resolve to the same public HTTPS origin so manual runs and webhook traffic return to the reachable server address.",
  },
] as const;

type ConnectionMode = "existing" | "new";

function readMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const record = payload as Record<string, unknown>;
  if (typeof record.message === "string" && record.message.trim()) return record.message;
  if (record.detail && typeof record.detail === "object") {
    const detailMessage = (record.detail as Record<string, unknown>).message;
    if (typeof detailMessage === "string" && detailMessage.trim()) return detailMessage;
  }
  if (typeof record.detail === "string" && record.detail.trim()) return record.detail;
  return fallback;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}

function readStringArray(record: Record<string, unknown> | null, ...keys: string[]): string[] {
  for (const key of keys) {
    const value = record?.[key];
    if (Array.isArray(value)) {
      return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
    }
  }
  return [];
}

function normalizeSetupStage(value: unknown): N8nSetupGuideStage | null {
  const record = asRecord(value);
  if (!record) return null;
  const stage = readString(record, "stage");
  const title = readString(record, "title");
  const summary = readString(record, "summary");
  if (
    !stage ||
    !title ||
    !summary ||
    typeof record.schemaVersion !== "string" ||
    typeof record.source !== "string" ||
    typeof record.stageIndex !== "number" ||
    typeof record.totalStages !== "number" ||
    !Array.isArray(record.instructions) ||
    !Array.isArray(record.commands) ||
    !Array.isArray(record.files) ||
    !Array.isArray(record.expectedSignals) ||
    !Array.isArray(record.troubleshooting) ||
    !Array.isArray(record.safetyNotes) ||
    typeof record.waitForPastedOutput !== "boolean"
  ) {
    return null;
  }

  const commands = record.commands.map(asRecord);
  const files = record.files.map(asRecord);
  if (
    commands.some((item) => !readString(item, "description") || !readString(item, "command")) ||
    files.some(
      (item) =>
        !readString(item, "path") ||
        !readString(item, "description") ||
        typeof item?.content !== "string"
    )
  ) {
    return null;
  }

  const askForRecord = record.askFor == null ? null : asRecord(record.askFor);
  if (record.askFor != null && (!readString(askForRecord, "field") || !readString(askForRecord, "question"))) {
    return null;
  }

  return {
    schemaVersion: record.schemaVersion,
    source: record.source,
    stage,
    stageIndex: record.stageIndex,
    totalStages: record.totalStages,
    title,
    summary,
    instructions: readStringArray(record, "instructions"),
    commands: commands.map((item) => ({
      description: readString(item, "description")!,
      command: readString(item, "command")!,
    })),
    files: files.map((item) => ({
      path: readString(item, "path")!,
      description: readString(item, "description")!,
      content: item!.content as string,
    })),
    expectedSignals: readStringArray(record, "expectedSignals"),
    troubleshooting: readStringArray(record, "troubleshooting"),
    safetyNotes: readStringArray(record, "safetyNotes"),
    askFor: askForRecord
      ? { field: readString(askForRecord, "field")!, question: readString(askForRecord, "question")! }
      : null,
    waitForPastedOutput: record.waitForPastedOutput,
    nextStage: typeof record.nextStage === "string" ? record.nextStage : null,
  };
}

function normalizeCheckResult(payload: unknown): N8nInstanceCheckResult | null {
  const outer = asRecord(payload);
  const record = asRecord(outer?.instance) ?? outer;
  if (!record) return null;
  const connectionStatus = readString(record, "connection_status", "connectionStatus", "status") ?? "checking";
  return {
    displayName: readString(record, "display_name", "displayName"),
    displayHost: readString(record, "display_host", "displayHost"),
    connectionStatus,
    compatibilityStatus:
      readString(record, "compatibility_status", "compatibilityStatus") ??
      (connectionStatus === "connected" ? "supported" : undefined),
    detectedVersion: readString(record, "version", "detected_version", "detectedVersion", "n8n_version", "n8nVersion"),
    capabilities: readStringArray(record, "capabilities"),
    verifiedAt: readString(record, "verified_at", "verifiedAt") ?? null,
    lastErrorCode: readString(record, "last_error_code", "lastErrorCode") ?? null,
    lastErrorMessage: readString(record, "last_error_message", "lastErrorMessage", "message") ?? null,
    message: readString(record, "message") ?? null,
  };
}

function formatDate(value?: string | null): string {
  if (!value) return "Not checked yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not checked yet";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function connectionVariant(status?: string) {
  if (status === "connected") return "success" as const;
  if (status === "checking") return "outline" as const;
  return "warning" as const;
}

function connectionLabel(status?: string) {
  switch (status) {
    case "connected":
      return "Connected";
    case "auth_invalid":
      return "API key invalid";
    case "unreachable":
      return "Server unreachable";
    case "unsupported":
    case "n8n_version_unsupported":
      return "Unsupported version";
    case "checking":
      return "Checking";
    default:
      return "Disconnected";
  }
}

function extractGuide(payload: unknown): N8nSetupGuidePayload | null {
  const record = asRecord(payload);
  if (!record) return null;
  const rawStages = Array.isArray(record.stages) ? record.stages : [];
  const stages = rawStages.map(normalizeSetupStage);

  const supportedTarget = asRecord(record.supportedTarget);
  if (
    typeof record.schemaVersion !== "string" ||
    typeof record.source !== "string" ||
    !supportedTarget ||
    stages.length === 0 ||
    stages.some((stage) => stage === null)
  ) {
    return null;
  }

  return {
    schemaVersion: record.schemaVersion,
    source: record.source,
    totalStages: typeof record.totalStages === "number" ? record.totalStages : stages.length,
    supportedTarget: {
      os: readString(supportedTarget, "os") ?? "",
      preferredOs: readString(supportedTarget, "preferredOs") ?? "",
      supportedOsVersions: readStringArray(supportedTarget, "supportedOsVersions"),
      architecture: readString(supportedTarget, "architecture") ?? "",
      hosting: readString(supportedTarget, "hosting") ?? "",
      dns: readString(supportedTarget, "dns") ?? "",
      ports: readString(supportedTarget, "ports") ?? "",
      baselineResources: readString(supportedTarget, "baselineResources") ?? "",
      n8nVersion: readString(supportedTarget, "n8nVersion") ?? "",
    },
    stages: stages as N8nSetupGuideStage[],
  };
}

async function authJson<T>(token: string, url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = (await response.json().catch(() => null)) as T | null;
  if (!response.ok) {
    throw new Error(readMessage(payload, "Request failed."));
  }
  return (payload ?? {}) as T;
}

function isValidDnsHostname(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  if (!normalized || normalized.length > 253 || normalized.includes("_")) return false;
  if (normalized.endsWith(".")) return false;
  const labels = normalized.split(".");
  if (labels.length < 2) return false;
  return labels.every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
}

function extractHostnameFromUrl(value: string): string {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function suggestedStageForError(code: string | null | undefined): string | null {
  switch (code) {
    case "n8n_connection_required":
      return "handoff_to_conduut";
    case "n8n_auth_invalid":
      return "handoff_to_conduut";
    case "n8n_unreachable":
      return "verify_stack";
    case "n8n_version_unsupported":
    case "n8n_version_unverifiable":
      return "deploy_n8n";
    case "n8n_capability_missing":
      return "verify_stack";
    default:
      return null;
  }
}

function stageButtonLabel(mode: ConnectionMode) {
  return mode === "existing" ? "Connect existing n8n" : "Set up a new n8n";
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      toast.error("Clipboard copy failed.");
    }
  };

  return (
    <Button type="button" variant="outline" size="sm" className="h-8 gap-1.5" onClick={() => void handleCopy()}>
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "Copied" : label}
    </Button>
  );
}

function CodeBlock({ text }: { text: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-[#0b1020] text-white">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="text-[11px] uppercase tracking-[0.16em] text-white/65">Command</span>
        <CopyButton text={text} />
      </div>
      <pre className="overflow-x-auto p-3 text-[12px] leading-6 whitespace-pre-wrap break-words">
        <code>{text}</code>
      </pre>
    </div>
  );
}

function FileBlock({ path, description, content }: { path: string; description: string; content: string }) {
  return (
    <div className="rounded-xl border border-border bg-muted/20">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <p className="text-[13px] font-medium text-foreground">{path}</p>
          <p className="mt-1 text-[12px] text-muted-foreground">{description}</p>
        </div>
        <CopyButton text={content} label="Copy file" />
      </div>
      <pre className="overflow-x-auto px-4 py-3 text-[12px] leading-6 whitespace-pre-wrap break-words text-foreground">
        <code>{content}</code>
      </pre>
    </div>
  );
}

function SetupGuide({
  guide,
  loading,
  error,
  expanded,
  onToggleExpanded,
  hostname,
  onHostnameChange,
  activeErrorCode,
}: {
  guide: N8nSetupGuidePayload | null;
  loading: boolean;
  error: string | null;
  expanded: boolean;
  onToggleExpanded: () => void;
  hostname: string;
  onHostnameChange: (value: string) => void;
  activeErrorCode?: string | null;
}) {
  const trimmedHostname = hostname.trim().toLowerCase();
  const safeHostname = isValidDnsHostname(trimmedHostname) ? trimmedHostname : "";
  const suggestedStage = useMemo(() => suggestedStageForError(activeErrorCode), [activeErrorCode]);

  return (
    <Card>
      <CardContent className="flex flex-col gap-5 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-conduut-500/10 text-conduut-600">
                <TerminalSquare className="h-4 w-4" />
              </span>
              <div>
                <p className="text-[15px] font-medium text-foreground">Set up a new n8n</p>
                <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                  Follow the same allowlisted guide the agent uses in chat. Conduut never asks for VPS passwords, private SSH keys, or your n8n API key here.
                </p>
              </div>
            </div>
          </div>
          <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={onToggleExpanded}>
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            {expanded ? "Hide guide" : "Show guide"}
          </Button>
        </div>

        {!expanded ? (
          <div className="rounded-xl border border-border bg-muted/20 p-4 text-[13px] leading-6 text-muted-foreground">
            The full setup guide is available here whenever you need to prepare a new VPS. You can also open the chat-assisted version if you prefer step-by-step back-and-forth.
          </div>
        ) : null}

        {expanded ? (
          <>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "Supported OS", value: guide?.supportedTarget.os ?? "Loading..." },
                { label: "Architecture", value: guide?.supportedTarget.architecture ?? "Loading..." },
                { label: "Public network", value: guide?.supportedTarget.ports ?? "Loading..." },
                { label: "Recommended baseline", value: guide?.supportedTarget.baselineResources ?? "Loading..." },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-border bg-muted/20 p-4">
                  <p className="text-[12px] text-muted-foreground">{item.label}</p>
                  <p className="mt-1 text-[13px] leading-5 text-foreground">{item.value}</p>
                </div>
              ))}
            </div>

            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-foreground">Public hostname for command substitution</span>
              <Input
                value={hostname}
                onChange={(event) => onHostnameChange(event.target.value)}
                placeholder="n8n.example.com"
                error={hostname.length > 0 && !safeHostname}
              />
              <p className="text-[12px] leading-5 text-muted-foreground">
                Only a normal public DNS hostname is substituted into the commands below. If the value is not a safe hostname, the guide keeps the literal <code>&lt;your-hostname&gt;</code> placeholder.
              </p>
            </label>

            {suggestedStage && guide ? (
              <div className="rounded-xl border border-warning/30 bg-warning-light/40 p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 text-warning" />
                  <div>
                    <p className="text-[13px] font-medium text-foreground">Start from the relevant step</p>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      Your latest server error maps most closely to{" "}
                      {guide.stages.find((stage) => stage.stage === suggestedStage)?.title ?? suggestedStage}.
                    </p>
                  </div>
                </div>
              </div>
            ) : null}

            {loading ? (
              <div className="rounded-xl border border-border bg-muted/20 p-4 text-[13px] text-muted-foreground">
                Loading the canonical setup guide...
              </div>
            ) : null}

            {error ? (
              <div className="rounded-xl border border-warning/40 bg-warning-light/40 p-4 text-[13px] text-warning">
                {error}
              </div>
            ) : null}

            {guide ? (
              <div className="flex flex-col gap-4">
                {guide.stages.map((stage) => {
                  const isSuggested = stage.stage === suggestedStage;
                  return (
                    <div
                      key={stage.stage}
                      className={cn(
                        "rounded-2xl border p-5",
                        isSuggested ? "border-warning/40 bg-warning-light/20" : "border-border bg-card"
                      )}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={isSuggested ? "warning" : "outline"}>
                              Step {stage.stageIndex} / {stage.totalStages}
                            </Badge>
                            {stage.nextStage ? <Badge variant="outline">Next: {stage.nextStage}</Badge> : <Badge variant="success">Final step</Badge>}
                          </div>
                          <p className="mt-3 text-[15px] font-medium text-foreground">{stage.title}</p>
                          <p className="mt-1 text-[13px] leading-6 text-muted-foreground">{stage.summary}</p>
                        </div>
                        {stage.waitForPastedOutput ? (
                          <Badge variant="outline">Pause for output</Badge>
                        ) : null}
                      </div>

                      {stage.askFor ? (
                        <div className="mt-4 rounded-xl border border-border bg-muted/20 p-4">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">Ask first</p>
                          <p className="mt-1 text-[13px] leading-6 text-foreground">{stage.askFor.question}</p>
                        </div>
                      ) : null}

                      {stage.instructions.length > 0 ? (
                        <div className="mt-4">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">What to do</p>
                          <div className="mt-2 space-y-2">
                            {stage.instructions.map((instruction) => (
                              <div key={instruction} className="rounded-xl border border-border bg-muted/20 px-4 py-3 text-[13px] leading-6 text-foreground">
                                {safeHostname ? instruction.replaceAll("<your-hostname>", safeHostname) : instruction}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {stage.commands.length > 0 ? (
                        <div className="mt-4 space-y-3">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">Commands</p>
                          {stage.commands.map((command) => {
                            const commandText = safeHostname
                              ? command.command.replaceAll("<your-hostname>", safeHostname)
                              : command.command;
                            return (
                              <div key={`${stage.stage}-${command.description}`} className="space-y-2">
                                <p className="text-[13px] font-medium text-foreground">{command.description}</p>
                                <CodeBlock text={commandText} />
                              </div>
                            );
                          })}
                        </div>
                      ) : null}

                      {stage.files.length > 0 ? (
                        <div className="mt-4 space-y-3">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">Files</p>
                          {stage.files.map((file) => {
                            const fileContent = safeHostname
                              ? file.content.replaceAll("<your-hostname>", safeHostname)
                              : file.content;
                            return (
                              <FileBlock
                                key={`${stage.stage}-${file.path}`}
                                path={file.path}
                                description={file.description}
                                content={fileContent}
                              />
                            );
                          })}
                        </div>
                      ) : null}

                      <div className="mt-4 grid gap-4 lg:grid-cols-3">
                        <div className="rounded-xl border border-border bg-muted/20 p-4">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">Expected signals</p>
                          <div className="mt-2 space-y-2">
                            {stage.expectedSignals.map((signal) => (
                              <div key={signal} className="flex items-start gap-2 text-[13px] leading-6 text-foreground">
                                <CheckCircle2 className="mt-1 h-3.5 w-3.5 shrink-0 text-conduut-600" />
                                <span>{safeHostname ? signal.replaceAll("<your-hostname>", safeHostname) : signal}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-xl border border-border bg-muted/20 p-4">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">Troubleshooting</p>
                          <div className="mt-2 space-y-2">
                            {stage.troubleshooting.map((item) => (
                              <div key={item} className="flex items-start gap-2 text-[13px] leading-6 text-foreground">
                                <AlertTriangle className="mt-1 h-3.5 w-3.5 shrink-0 text-warning" />
                                <span>{safeHostname ? item.replaceAll("<your-hostname>", safeHostname) : item}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-xl border border-border bg-muted/20 p-4">
                          <p className="text-[12px] uppercase tracking-[0.14em] text-muted-foreground">Safety</p>
                          <div className="mt-2 space-y-2">
                            {stage.safetyNotes.map((item) => (
                              <div key={item} className="flex items-start gap-2 text-[13px] leading-6 text-foreground">
                                <ShieldAlert className="mt-1 h-3.5 w-3.5 shrink-0 text-conduut-600" />
                                <span>{safeHostname ? item.replaceAll("<your-hostname>", safeHostname) : item}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-conduut-500/20 bg-conduut-500/[0.04] p-4">
          <div className="flex items-start gap-3">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-conduut-500/10 text-conduut-600">
              <FileText className="h-4 w-4" />
            </span>
            <div>
              <p className="text-[14px] font-medium text-foreground">Prefer the chat-assisted version?</p>
              <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                The chat route uses the same canonical guide and keeps the same no-secret boundary.
              </p>
            </div>
          </div>
          <Link
            href="/chat?intent=automation-server-setup"
            className="inline-flex h-8 items-center justify-center rounded-lg bg-conduut-500 px-3 text-[13px] font-medium text-white shadow-sm transition-all duration-150 hover:bg-conduut-700 active:scale-[0.97]"
          >
            Open in chat
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export function AutomationServerSection() {
  const { user } = useAuth();
  const { instance, loading: instanceLoading, error: instanceError, refresh: refreshInstance } = useN8nInstance();

  const [displayName, setDisplayName] = useState("Automation server");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [rotateApiKey, setRotateApiKey] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [checkResult, setCheckResult] = useState<N8nInstanceCheckResult | null>(null);
  const [guide, setGuide] = useState<N8nSetupGuidePayload | null>(null);
  const [guideLoading, setGuideLoading] = useState(true);
  const [guideError, setGuideError] = useState<string | null>(null);
  const [mode, setMode] = useState<ConnectionMode>("existing");
  const [guideExpanded, setGuideExpanded] = useState(false);
  const [hostname, setHostname] = useState("");
  const [baseUrlTouched, setBaseUrlTouched] = useState(false);

  useEffect(() => {
    if (!instance) return;
    setDisplayName(instance.displayName || "Automation server");
  }, [instance]);

  useEffect(() => {
    if (isN8nConnected(instance)) {
      setGuideExpanded(false);
    }
  }, [instance]);

  useEffect(() => {
    if (!instance) return;
    const host = instance.displayHost?.split("/")[0] ?? "";
    if (host && isValidDnsHostname(host) && !hostname) {
      setHostname(host);
    }
  }, [hostname, instance]);

  const suggestedBaseUrl = useMemo(() => {
    const candidate = hostname.trim().toLowerCase();
    return isValidDnsHostname(candidate) ? `https://${candidate}` : "";
  }, [hostname]);

  useEffect(() => {
    if (!suggestedBaseUrl || baseUrlTouched || baseUrl.trim()) return;
    setBaseUrl(suggestedBaseUrl);
  }, [baseUrl, baseUrlTouched, suggestedBaseUrl]);

  useEffect(() => {
    let cancelled = false;

    async function loadGuide() {
      if (!user) {
        setGuide(null);
        setGuideError(null);
        setGuideLoading(false);
        return;
      }

      setGuideLoading(true);
      setGuideError(null);
      try {
        const token = await user.getIdToken();
        const response = await fetch("/api/n8n/setup-guide", {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(readMessage(payload, "The setup guide could not be loaded."));
        }
        const normalized = extractGuide(payload);
        if (!normalized) {
          throw new Error("The setup guide response was incomplete.");
        }
        if (!cancelled) {
          setGuide(normalized);
        }
      } catch (error) {
        if (!cancelled) {
          setGuide(null);
          setGuideError(error instanceof Error ? error.message : "The setup guide could not be loaded.");
        }
      } finally {
        if (!cancelled) {
          setGuideLoading(false);
        }
      }
    }

    void loadGuide();

    return () => {
      cancelled = true;
    };
  }, [user]);

  const connectionStatus = checkResult?.connectionStatus ?? instance?.connectionStatus ?? "disconnected";
  const latestErrorCode = checkResult?.lastErrorCode ?? instance?.lastErrorCode ?? null;
  const showConnectionPrompt = !instanceLoading && (!instance || isN8nConnectionIssue(instance.connectionStatus));

  const handleCheck = async () => {
    if (!user || !instance) return;
    setChecking(true);
    try {
      const token = await user.getIdToken();
      const payload = await authJson<Record<string, unknown>>(token, "/api/n8n/instance/check", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setCheckResult(normalizeCheckResult(payload));
      toast.success("Automation server checked.");
    } catch (error) {
      setCheckResult(null);
      toast.error(error instanceof Error ? error.message : "Automation server could not be checked.");
    } finally {
      setChecking(false);
    }
  };

  const handleConnect = async () => {
    if (!user) return;
    if (!baseUrl.trim() || !apiKey.trim()) {
      toast.error("Enter both the server URL and API key first.");
      return;
    }
    setSaving(true);
    try {
      const token = await user.getIdToken();
      await authJson<Record<string, unknown>>(token, "/api/n8n/instance", {
        method: "POST",
        body: JSON.stringify({
          displayName: displayName.trim() || "Automation server",
          baseUrl: baseUrl.trim(),
          apiKey,
        }),
      });
      setApiKey("");
      setCheckResult(null);
      await refreshInstance();
      toast.success("Automation server connected.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Automation server could not be connected.");
    } finally {
      setSaving(false);
    }
  };

  const handleRotateKey = async () => {
    if (!user) return;
    if (!rotateApiKey.trim()) {
      toast.error("Enter the new API key first.");
      return;
    }
    setRotating(true);
    try {
      const token = await user.getIdToken();
      await authJson<Record<string, unknown>>(token, "/api/n8n/instance/key", {
        method: "PUT",
        body: JSON.stringify({ apiKey: rotateApiKey }),
      });
      setRotateApiKey("");
      await refreshInstance();
      toast.success("API key rotated.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "API key could not be rotated.");
    } finally {
      setRotating(false);
    }
  };

  const handleDisconnect = async () => {
    if (!user) return;
    setDisconnecting(true);
    try {
      const token = await user.getIdToken();
      await authJson<Record<string, unknown>>(token, "/api/n8n/instance", {
        method: "DELETE",
      });
      setApiKey("");
      setRotateApiKey("");
      setCheckResult(null);
      setBaseUrlTouched(false);
      await refreshInstance();
      toast.success("Automation server disconnected.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Automation server could not be disconnected.");
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <div className="flex max-w-5xl flex-col gap-5">
      {showConnectionPrompt ? (
        <ConnectionCallout
          compact
          statusLabel={instance?.connectionStatus ? connectionLabel(instance.connectionStatus) : undefined}
        />
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.95fr)]">
        <Card>
          <CardContent className="flex flex-col gap-5 p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4 text-conduut-500" />
                  <h2 className="text-[15px] font-medium text-foreground">Automation Server</h2>
                </div>
                <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                  Connect your own n8n instance so Conduut can inspect workflows, manage credentials, and run jobs through your server.
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => void refreshInstance()} disabled={instanceLoading}>
                <RefreshCw className={cn("h-3.5 w-3.5", instanceLoading && "animate-spin")} />
                Refresh
              </Button>
            </div>

            {!isN8nConnected(instance) ? (
              <div className="flex w-fit items-center gap-1 rounded-lg border border-border bg-card p-1">
                {(["existing", "new"] as ConnectionMode[]).map((nextMode) => (
                  <button
                    type="button"
                    key={nextMode}
                    onClick={() => {
                      setMode(nextMode);
                      setGuideExpanded(nextMode === "new");
                    }}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                      mode === nextMode ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {stageButtonLabel(nextMode)}
                  </button>
                ))}
              </div>
            ) : null}

            {isN8nConnected(instance) ? (
              <div className="rounded-xl border border-conduut-500/20 bg-conduut-500/5 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-conduut-500/10 text-conduut-600">
                      <CheckCircle2 className="h-4 w-4" />
                    </span>
                    <div>
                      <p className="text-[13px] font-medium text-foreground">Your server is connected</p>
                      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                        Conduut uses this server for workflows, runs, and credentials. See Current status for diagnostics.
                      </p>
                    </div>
                  </div>
                  <Button type="button" variant="outline" size="sm" disabled={checking} onClick={() => void handleCheck()}>
                    {checking ? "Refreshing..." : "Refresh health"}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <div className="rounded-xl border border-border bg-muted/20 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-[14px] font-medium text-foreground">Connection details</p>
                      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                        Paste the public URL and a newly created admin API key for the n8n instance you want Conduut to use.
                      </p>
                    </div>
                    <Badge variant="outline">n8n {CANONICAL_N8N_VERSION}</Badge>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="flex flex-col gap-1.5">
                    <span className="text-[13px] font-medium text-foreground">Display name</span>
                    <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Automation server" />
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className="text-[13px] font-medium text-foreground">n8n URL</span>
                    <Input
                      value={baseUrl}
                      onChange={(event) => {
                        setBaseUrl(event.target.value);
                        setBaseUrlTouched(true);
                        const host = extractHostnameFromUrl(event.target.value);
                        if (host && isValidDnsHostname(host)) {
                          setHostname(host);
                        }
                      }}
                      placeholder={suggestedBaseUrl || "https://automation.example.com"}
                    />
                    {suggestedBaseUrl ? (
                      <p className="text-[12px] leading-5 text-muted-foreground">
                        Suggested from the setup guide hostname: {suggestedBaseUrl}
                      </p>
                    ) : null}
                  </label>
                </div>

                <label className="flex flex-col gap-1.5">
                  <span className="text-[13px] font-medium text-foreground">API key</span>
                  <Input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste a newly created API key" />
                  <p className="text-[12px] leading-5 text-muted-foreground">
                    Conduut accepts the key once for verification and storage. It is never returned in API responses or shown again in the UI.
                  </p>
                </label>

                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" size="sm" disabled={checking || saving} onClick={() => void handleConnect()}>
                    {saving ? "Saving..." : "Connect"}
                  </Button>
                  {mode === "new" ? (
                    <Button type="button" variant="outline" size="sm" onClick={() => setGuideExpanded(true)}>
                      View setup guide
                    </Button>
                  ) : null}
                </div>
              </>
            )}

            {checkResult ? (
              <div className="rounded-xl border border-border bg-muted/20 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-[14px] font-medium text-foreground">Health check result</p>
                  <Badge variant={connectionVariant(checkResult.connectionStatus)}>
                    {connectionLabel(checkResult.connectionStatus)}
                  </Badge>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-[12px] text-muted-foreground">Version</p>
                    <p className="text-[13px] text-foreground">{checkResult.detectedVersion || "Unknown"}</p>
                  </div>
                  <div>
                    <p className="text-[12px] text-muted-foreground">Compatibility</p>
                    <p className="text-[13px] text-foreground">{checkResult.compatibilityStatus || "Unchecked"}</p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="text-[12px] text-muted-foreground">Capabilities</p>
                    <p className="text-[13px] text-foreground">
                      {checkResult.capabilities.length > 0 ? checkResult.capabilities.join(", ") : "No capabilities reported yet."}
                    </p>
                  </div>
                  {checkResult.lastErrorMessage ? (
                    <div className="sm:col-span-2">
                      <p className="text-[12px] text-muted-foreground">Details</p>
                      <p className="text-[13px] text-foreground">{checkResult.lastErrorMessage}</p>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            {instanceError ? (
              <div className="rounded-xl border border-warning/40 bg-warning-light/40 p-3 text-[13px] text-warning">
                {instanceError}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-5">
          <Card>
            <CardContent className="flex flex-col gap-4 p-6">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[15px] font-medium text-foreground">Current status</p>
                <Badge variant={connectionVariant(connectionStatus)}>{connectionLabel(connectionStatus)}</Badge>
              </div>

              {instance ? (
                <div className="grid gap-3 text-[13px]">
                  <div>
                    <p className="text-[12px] text-muted-foreground">Server</p>
                    <p className="truncate text-foreground">{instance.displayName}</p>
                  </div>
                  <div>
                    <p className="text-[12px] text-muted-foreground">Host</p>
                    <p className="truncate text-foreground">{instance.displayHost || "Hidden after connect"}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <p className="text-[12px] text-muted-foreground">Version</p>
                      <p className="text-foreground">{instance.detectedVersion || "Unknown"}</p>
                    </div>
                    <div>
                      <p className="text-[12px] text-muted-foreground">Compatibility</p>
                      <p className="text-foreground">{instance.compatibilityStatus || "Unchecked"}</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-[12px] text-muted-foreground">Last checked</p>
                    <p className="text-foreground">{formatDate(instance.verifiedAt || instance.lastHealthAt)}</p>
                  </div>
                  <div>
                    <p className="text-[12px] text-muted-foreground">Capabilities</p>
                    <p className="text-foreground">
                      {instance.capabilities.length > 0 ? instance.capabilities.join(", ") : "No capabilities reported yet."}
                    </p>
                  </div>
                  {instance.lastErrorCode ? (
                    <div className="rounded-lg border border-warning/30 bg-warning-light/40 p-3">
                      <div className="flex items-center gap-2">
                        <ShieldAlert className="h-4 w-4 text-warning" />
                        <p className="text-[13px] font-medium text-foreground">Latest issue</p>
                      </div>
                      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                        {instance.lastErrorMessage || instance.lastErrorCode}
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="text-[13px] leading-6 text-muted-foreground">
                  No automation server is connected yet. Add your URL and API key to start using workflows and runs from this dashboard.
                </p>
              )}
            </CardContent>
          </Card>

          {instance ? (
            <Card>
              <CardContent className="flex flex-col gap-4 p-6">
                <p className="text-[15px] font-medium text-foreground">Rotate or disconnect</p>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[13px] font-medium text-foreground">New API key</span>
                  <Input type="password" value={rotateApiKey} onChange={(event) => setRotateApiKey(event.target.value)} placeholder="Paste the replacement key" />
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" disabled={rotating || disconnecting} onClick={() => void handleRotateKey()}>
                    {rotating ? "Rotating..." : "Rotate key"}
                  </Button>
                  <Button type="button" variant="outline" size="sm" disabled={rotating || disconnecting} onClick={() => void handleDisconnect()}>
                    {disconnecting ? "Disconnecting..." : "Disconnect"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 p-6">
          <div>
            <p className="text-[15px] font-medium text-foreground">What Conduut expects</p>
            <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
              Your automation server should meet these requirements for a reliable connection.
            </p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {AUTOMATION_SERVER_EXPECTATIONS.map((item) => (
              <div key={item.title} className="rounded-xl border border-border bg-muted/20 p-4">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-conduut-500/10 text-conduut-600">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  </span>
                  <div>
                    <p className="text-[13px] font-medium text-foreground">{item.title}</p>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{item.description}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <SetupGuide
        guide={guide}
        loading={guideLoading}
        error={guideError}
        expanded={guideExpanded}
        onToggleExpanded={() => setGuideExpanded((value) => !value)}
        hostname={hostname}
        onHostnameChange={setHostname}
        activeErrorCode={latestErrorCode}
      />
    </div>
  );
}
