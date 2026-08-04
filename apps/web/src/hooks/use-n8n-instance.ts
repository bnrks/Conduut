"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/hooks/use-auth";
import type { N8nConnectionStatus, N8nInstance } from "@/types/n8n";
import { isN8nConnected, isN8nConnectionIssue } from "@/types/n8n";

interface N8nInstanceState {
  instance: N8nInstance | null;
  loading: boolean;
  error: string | null;
  connected: boolean;
  connectionRequired: boolean;
  refresh: () => Promise<void>;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
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

function extractMessage(payload: Record<string, unknown> | null, fallback: string): string {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    const detailRecord = detail as Record<string, unknown>;
    if (typeof detailRecord.message === "string" && detailRecord.message.trim()) {
      return detailRecord.message;
    }
  }
  if (typeof payload?.message === "string" && payload.message.trim()) return payload.message;
  return fallback;
}

function extractCode(payload: Record<string, unknown> | null): string | undefined {
  const detail = payload?.detail;
  if (detail && typeof detail === "object") {
    const code = (detail as Record<string, unknown>).code;
    if (typeof code === "string" && code.trim()) return code;
  }
  const code = payload?.code;
  return typeof code === "string" && code.trim() ? code : undefined;
}

function normalizeInstance(payload: Record<string, unknown> | null): N8nInstance | null {
  if (!payload) return null;
  const instanceRecord = asRecord(payload.instance) ?? payload;
  const displayHost = readString(instanceRecord, "display_host", "displayHost");
  const displayName = readString(instanceRecord, "display_name", "displayName") ?? "Automation server";
  const connectionStatus =
    (readString(instanceRecord, "connection_status", "connectionStatus", "status") as N8nConnectionStatus | undefined) ??
    "disconnected";

  if (!displayHost && connectionStatus === "disconnected") {
    return null;
  }

  return {
    id: readString(instanceRecord, "id", "instance_id", "instanceId"),
    displayName,
    displayHost,
    webhookBaseUrl: readString(instanceRecord, "webhook_base_url", "webhookBaseUrl"),
    ownership: readString(instanceRecord, "ownership"),
    provider: readString(instanceRecord, "provider"),
    connectionStatus,
    compatibilityStatus:
      readString(instanceRecord, "compatibility_status", "compatibilityStatus") ??
      (connectionStatus === "connected" ? "supported" : undefined),
    detectedVersion: readString(
      instanceRecord,
      "version",
      "detected_version",
      "detectedVersion",
      "n8n_version",
      "n8nVersion"
    ),
    capabilities: readStringArray(instanceRecord, "capabilities"),
    lastErrorCode: readString(instanceRecord, "last_error_code", "lastErrorCode") ?? null,
    lastErrorMessage: readString(instanceRecord, "last_error_message", "lastErrorMessage") ?? null,
    verifiedAt: readString(instanceRecord, "verified_at", "verifiedAt") ?? null,
    lastHealthAt: readString(instanceRecord, "last_health_at", "lastHealthAt") ?? null,
    createdAt: readString(instanceRecord, "created_at", "createdAt") ?? null,
    updatedAt: readString(instanceRecord, "updated_at", "updatedAt") ?? null,
  };
}

export function useN8nInstance(): N8nInstanceState {
  const { user, loading: authLoading } = useAuth();
  const [instance, setInstance] = useState<N8nInstance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionRequired, setConnectionRequired] = useState(false);

  const refresh = useCallback(async () => {
    if (authLoading) return;
    if (!user) {
      setInstance(null);
      setError(null);
      setConnectionRequired(false);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const token = await user.getIdToken();
      const response = await fetch("/api/n8n/instance", {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;

      if (!response.ok) {
        const code = extractCode(payload);
        const message = extractMessage(payload, "Automation server status could not be loaded.");
        if (
          response.status === 404 ||
          code === "n8n_connection_required" ||
          code === "connection_required"
        ) {
          setInstance(null);
          setConnectionRequired(true);
          setError(null);
          return;
        }
        setInstance(normalizeInstance(payload));
        setConnectionRequired(code === "n8n_connection_required" || code === "connection_required");
        setError(message);
        return;
      }

      const nextInstance = normalizeInstance(payload);
      setInstance(nextInstance);
      setConnectionRequired(!nextInstance || !isN8nConnected(nextInstance));
    } catch {
      setInstance(null);
      setConnectionRequired(false);
      setError("Automation server status could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [authLoading, user]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    instance,
    loading,
    error,
    connected: isN8nConnected(instance),
    connectionRequired: connectionRequired || isN8nConnectionIssue(instance?.connectionStatus),
    refresh,
  };
}
