"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, ExternalLink, RefreshCw, Server, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ConnectionCallout } from "@/components/n8n/connection-callout";
import { useAuth } from "@/hooks/use-auth";
import { useN8nInstance } from "@/hooks/use-n8n-instance";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";
import type { N8nInstanceCheckResult, N8nMigrationState } from "@/types/n8n";
import { isN8nConnected, isN8nConnectionIssue } from "@/types/n8n";

type Tab = "profile" | "security" | "preferences" | "automation-server";
type ThemeOption = "light" | "dark" | "system";
const CANONICAL_N8N_VERSION = "1.121.3";

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "security", label: "Security" },
  { key: "preferences", label: "Preferences" },
  { key: "automation-server", label: "Automation Server" },
];

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

function readNumber(record: Record<string, unknown> | null, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function readBoolean(record: Record<string, unknown> | null, ...keys: string[]): boolean | undefined {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "boolean") return value;
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

function normalizeMigrationState(payload: unknown): N8nMigrationState | null {
  const record = asRecord(payload);
  if (!record) return null;
  return {
    status: readString(record, "status") ?? "idle",
    message: readString(record, "message", "summary") ?? null,
    totalWorkflows: readNumber(record, "total_workflows", "totalWorkflows") ?? null,
    migratedWorkflows: readNumber(record, "migrated_workflows", "migratedWorkflows") ?? null,
    adoptedWorkflows: readNumber(record, "adopted_workflows", "adoptedWorkflows") ?? null,
    remainingWorkflows: readNumber(record, "remaining_workflows", "remainingWorkflows") ?? null,
    nextAction: readString(record, "next_action", "nextAction") ?? null,
    canStart: readBoolean(record, "can_start", "canStart") ?? false,
    canAdvance: readBoolean(record, "can_advance", "canAdvance") ?? false,
    updatedAt: readString(record, "updated_at", "updatedAt") ?? null,
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
      return "Unsupported version";
    case "checking":
      return "Checking";
    default:
      return "Disconnected";
  }
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

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const initialTab = searchParams.get("tab") === "automation-server" ? "automation-server" : "profile";
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const { instance, loading: instanceLoading, error: instanceError, refresh: refreshInstance } = useN8nInstance();

  const [name, setName] = useState(user?.displayName || "User");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailNotifications, setEmailNotifications] = useState(true);

  const [displayName, setDisplayName] = useState("Automation server");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [rotateApiKey, setRotateApiKey] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [checkResult, setCheckResult] = useState<N8nInstanceCheckResult | null>(null);
  const [migration, setMigration] = useState<N8nMigrationState | null>(null);
  const [migrationLoading, setMigrationLoading] = useState(false);
  const [migrationBusy, setMigrationBusy] = useState(false);

  useEffect(() => {
    setName(user?.displayName || "User");
  }, [user?.displayName]);

  useEffect(() => {
    if (searchParams.get("tab") === "automation-server") {
      setActiveTab("automation-server");
    }
  }, [searchParams]);

  useEffect(() => {
    if (!instance) return;
    setDisplayName(instance.displayName || "Automation server");
  }, [instance]);

  const loadMigration = useCallback(async () => {
    if (!user || !isN8nConnected(instance)) {
      setMigration(null);
      return;
    }
    setMigrationLoading(true);
    try {
      const token = await user.getIdToken();
      const payload = await authJson<Record<string, unknown>>(token, "/api/n8n/migration", {
        cache: "no-store",
      });
      setMigration(normalizeMigrationState(payload));
    } catch (error) {
      setMigration(null);
      toast.error(error instanceof Error ? error.message : "Migration status could not be loaded.");
    } finally {
      setMigrationLoading(false);
    }
  }, [instance, user]);

  useEffect(() => {
    if (user && isN8nConnected(instance)) {
      void loadMigration();
    } else {
      setMigration(null);
    }
  }, [instance, loadMigration, user]);

  const connectionStatus = checkResult?.connectionStatus ?? instance?.connectionStatus ?? "disconnected";
  const showConnectionPrompt =
    !instanceLoading && (!instance || isN8nConnectionIssue(instance.connectionStatus));
  const migrationProgress = useMemo(() => {
    if (!migration?.totalWorkflows || migration.totalWorkflows <= 0) return 0;
    const completed = migration.migratedWorkflows ?? migration.adoptedWorkflows ?? 0;
    return Math.max(0, Math.min(100, Math.round((completed / migration.totalWorkflows) * 100)));
  }, [migration]);

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
          apiKey: apiKey,
        }),
      });
      setApiKey("");
      setCheckResult(null);
      await refreshInstance();
      await loadMigration();
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
      setMigration(null);
      await refreshInstance();
      toast.success("Automation server disconnected.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Automation server could not be disconnected.");
    } finally {
      setDisconnecting(false);
    }
  };

  const handleMigrationAction = async (path: string, successMessage: string, body: Record<string, unknown>) => {
    if (!user) return;
    setMigrationBusy(true);
    try {
      const token = await user.getIdToken();
      const payload = await authJson<Record<string, unknown>>(token, path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setMigration(normalizeMigrationState(payload));
      await refreshInstance();
      toast.success(successMessage);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Migration request failed.");
    } finally {
      setMigrationBusy(false);
    }
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-medium text-foreground">Settings</h1>

      <div className="mb-6 flex w-fit items-center gap-1 rounded-lg border border-border bg-card p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "rounded-md px-4 py-1.5 text-[14px] font-medium transition-colors",
              activeTab === tab.key ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "profile" && (
        <Card className="max-w-lg">
          <CardContent className="flex flex-col gap-5 p-6">
            <h2 className="text-[15px] font-medium text-foreground">Profile Information</h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Name</label>
              <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Email</label>
              <Input value={user?.email ?? ""} disabled className="bg-muted" />
              <p className="text-[12px] text-muted-foreground">Email cannot be changed after registration.</p>
            </div>
            <div className="flex justify-end pt-1">
              <Button size="sm" onClick={() => console.log("Save profile:", name)}>
                Save Changes
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "security" && (
        <Card className="max-w-lg">
          <CardContent className="flex flex-col gap-5 p-6">
            <h2 className="text-[15px] font-medium text-foreground">Change Password</h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Current Password</label>
              <Input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} placeholder="Enter current password" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">New Password</label>
              <Input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="Enter new password" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Confirm New Password</label>
              <Input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Confirm new password"
                error={confirmPassword.length > 0 && confirmPassword !== newPassword}
              />
              {confirmPassword.length > 0 && confirmPassword !== newPassword ? (
                <p className="text-[12px] text-error">Passwords do not match.</p>
              ) : null}
            </div>
            <div className="flex justify-end pt-1">
              <Button
                size="sm"
                disabled={!currentPassword || !newPassword || newPassword !== confirmPassword}
                onClick={() => console.log("Update password")}
              >
                Update Password
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "preferences" && (
        <Card className="max-w-lg">
          <CardContent className="flex flex-col gap-6 p-6">
            <h2 className="text-[15px] font-medium text-foreground">Preferences</h2>

            <div className="flex flex-col gap-2">
              <label className="text-[13px] font-medium text-foreground">Theme</label>
              <div className="flex w-fit items-center gap-1 rounded-lg border border-border bg-muted p-1">
                {(["light", "dark", "system"] as ThemeOption[]).map((nextTheme) => (
                  <button
                    key={nextTheme}
                    onClick={() => setTheme(nextTheme)}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-[13px] font-medium capitalize transition-colors",
                      theme === nextTheme ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {nextTheme.charAt(0).toUpperCase() + nextTheme.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-medium text-foreground">Email Notifications</p>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  Receive emails about workflow errors and usage alerts.
                </p>
              </div>
              <button
                role="switch"
                aria-checked={emailNotifications}
                onClick={() => setEmailNotifications((value) => !value)}
                className={cn(
                  "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  emailNotifications ? "bg-conduut-500" : "bg-gray-200"
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm ring-0 transition-transform duration-200",
                    emailNotifications ? "translate-x-5" : "translate-x-0"
                  )}
                />
              </button>
            </div>

            <div className="flex justify-end border-t border-border pt-1">
              <Button size="sm" onClick={() => console.log("Save preferences:", { theme, emailNotifications })}>
                Save Preferences
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "automation-server" && (
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
                      Connect your own n8n instance so Conduut can inspect workflows, adopt existing automations, and run jobs through your server.
                    </p>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      BYO V1 currently requires canonical n8n version {CANONICAL_N8N_VERSION}. Other versions fail closed during connection checks.
                    </p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => void refreshInstance()} disabled={instanceLoading}>
                    <RefreshCw className={cn("h-3.5 w-3.5", instanceLoading && "animate-spin")} />
                    Refresh
                  </Button>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => setCheckResult(null)}
                    className="rounded-xl border border-border bg-muted/20 p-4 text-left transition-colors hover:bg-muted/40"
                  >
                    <p className="text-[14px] font-medium text-foreground">Connect existing n8n</p>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      Use your public HTTPS URL and an API key created in your own n8n admin account.
                    </p>
                  </button>
                  <div className="rounded-xl border border-border bg-muted/20 p-4">
                    <p className="text-[14px] font-medium text-foreground">Set up a new n8n</p>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      1. Provision a public HTTPS n8n server. 2. Finish your admin setup. 3. Create an API key. 4. Return here and connect it.
                    </p>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="flex flex-col gap-1.5">
                    <span className="text-[13px] font-medium text-foreground">Display name</span>
                    <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Automation server" />
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className="text-[13px] font-medium text-foreground">n8n URL</span>
                    <Input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://automation.example.com" />
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
                  <Button
                    type="button"
                    size="sm"
                    disabled={checking || saving || isN8nConnected(instance)}
                    onClick={() => void handleConnect()}
                  >
                    {saving ? "Saving…" : isN8nConnected(instance) ? "Connected" : "Connect"}
                  </Button>
                  {instance ? (
                    <Button type="button" variant="outline" size="sm" disabled={checking || saving} onClick={() => void handleCheck()}>
                      {checking ? "Refreshing…" : "Refresh health"}
                    </Button>
                  ) : null}
                </div>

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
                      {instance.lastErrorMessage ? (
                        <div className="rounded-lg border border-warning/30 bg-warning-light/40 p-3">
                          <div className="flex items-center gap-2">
                            <ShieldAlert className="h-4 w-4 text-warning" />
                            <p className="text-[13px] font-medium text-foreground">Latest issue</p>
                          </div>
                          <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{instance.lastErrorMessage}</p>
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
                        {rotating ? "Rotating…" : "Rotate key"}
                      </Button>
                      <Button type="button" variant="outline" size="sm" disabled={rotating || disconnecting} onClick={() => void handleDisconnect()}>
                        {disconnecting ? "Disconnecting…" : "Disconnect"}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ) : null}
            </div>
          </div>

          {instance && (
            <Card>
              <CardContent className="flex flex-col gap-4 p-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-[15px] font-medium text-foreground">Legacy workflow migration</p>
                    <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                      After you connect your own server, Conduut can help you confirm and advance any remaining workflow adoption steps.
                    </p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => void loadMigration()} disabled={migrationLoading || migrationBusy}>
                    <RefreshCw className={cn("h-3.5 w-3.5", (migrationLoading || migrationBusy) && "animate-spin")} />
                    Refresh
                  </Button>
                </div>

                {migration ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={migration.status === "completed" ? "success" : "outline"}>
                        {migration.status.replaceAll("_", " ")}
                      </Badge>
                      {migration.updatedAt ? (
                        <span className="text-[12px] text-muted-foreground">Updated {formatDate(migration.updatedAt)}</span>
                      ) : null}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-4">
                      <div className="rounded-lg border border-border bg-muted/20 p-3">
                        <p className="text-[11px] uppercase text-muted-foreground">Total</p>
                        <p className="mt-1 text-[15px] font-medium text-foreground">{migration.totalWorkflows ?? 0}</p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/20 p-3">
                        <p className="text-[11px] uppercase text-muted-foreground">Migrated</p>
                        <p className="mt-1 text-[15px] font-medium text-foreground">{migration.migratedWorkflows ?? 0}</p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/20 p-3">
                        <p className="text-[11px] uppercase text-muted-foreground">Adopted</p>
                        <p className="mt-1 text-[15px] font-medium text-foreground">{migration.adoptedWorkflows ?? 0}</p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/20 p-3">
                        <p className="text-[11px] uppercase text-muted-foreground">Remaining</p>
                        <p className="mt-1 text-[15px] font-medium text-foreground">{migration.remainingWorkflows ?? 0}</p>
                      </div>
                    </div>
                    <div>
                      <div className="mb-2 flex items-center justify-between text-[12px] text-muted-foreground">
                        <span>Progress</span>
                        <span>{migrationProgress}%</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-conduut-500 transition-all duration-300" style={{ width: `${migrationProgress}%` }} />
                      </div>
                    </div>
                    {migration.message ? (
                      <div className="rounded-lg border border-border bg-muted/20 p-3 text-[13px] leading-6 text-muted-foreground">
                        {migration.message}
                      </div>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-2">
                      {migration.canStart ? (
                        <Button size="sm" disabled={migrationBusy} onClick={() => void handleMigrationAction("/api/n8n/migration/start", "Migration started.", { confirm: true })}>
                          Start migration
                        </Button>
                      ) : null}
                      {migration.canAdvance ? (
                        <Button variant="outline" size="sm" disabled={migrationBusy} onClick={() => void handleMigrationAction("/api/n8n/migration/advance", "Migration advanced.", {})}>
                          Continue migration
                        </Button>
                      ) : null}
                      {migration.nextAction ? (
                        <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
                          <CheckCircle2 className="h-3.5 w-3.5 text-conduut-500" />
                          Next: {migration.nextAction}
                        </span>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="rounded-lg border border-border bg-muted/20 p-4 text-[13px] leading-6 text-muted-foreground">
                    {migrationLoading
                      ? "Loading migration status…"
                      : "No migration status is available yet. Connect your server first, then refresh this section to confirm whether any legacy workflows need adoption."}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="flex flex-col gap-3 p-6">
              <div className="flex items-center gap-2">
                <p className="text-[15px] font-medium text-foreground">What Conduut expects</p>
                <a
                  href="https://n8n.io/"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[12px] text-conduut-500 hover:text-conduut-700"
                >
                  n8n
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
              <ul className="space-y-2 text-[13px] leading-6 text-muted-foreground">
                <li>Use a public HTTPS n8n URL that Conduut can reach from the server side.</li>
                <li>Create a fresh API key in your n8n admin account and keep it write-only in this form.</li>
                <li>After connecting, workflows that already live on your server can appear as read-only until you adopt them into Conduut metadata.</li>
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
