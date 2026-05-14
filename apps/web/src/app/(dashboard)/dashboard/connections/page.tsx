"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, Plug, Plus, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { ServiceLogo } from "@/components/dashboard/service-logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import type { AvailableService, Connection } from "@/types/connection";

const AVAILABLE_SERVICES: AvailableService[] = [
  {
    name: "Google Gmail",
    slug: "google-gmail",
    icon: "gmail",
    description: "Read and send Gmail messages from workflows",
    category: "Email",
    connectionId: "google_gmail",
    authorizePath: "/api/connections/google/gmail/authorize",
  },
  {
    name: "Google Sheets",
    slug: "google-sheets",
    icon: "google-sheets",
    description: "Read spreadsheet rows from workflows",
    category: "Data",
    connectionId: "google_sheets",
    authorizePath: "/api/connections/google/sheets/authorize",
  },
];

const GOOGLE_CAPABILITIES = [
  {
    id: "google.gmail.read",
    label: "Can read Gmail",
    description: "Read messages, threads, and labels in Gmail workflows",
    serviceSlug: "google-gmail",
    connectionId: "google_gmail",
  },
  {
    id: "google.gmail.send",
    label: "Can send Gmail",
    description: "Send or reply to messages from Gmail workflows",
    serviceSlug: "google-gmail",
    connectionId: "google_gmail",
  },
  {
    id: "google.sheets.read",
    label: "Can read Sheets",
    description: "Read spreadsheet rows in Sheets workflows",
    serviceSlug: "google-sheets",
    connectionId: "google_sheets",
  },
  {
    id: "google.sheets.write",
    label: "Can edit Sheets",
    description: "Create or update spreadsheet content in Sheets workflows",
    serviceSlug: "google-sheets",
    connectionId: "google_sheets",
  },
];

const DEFAULT_EXPANDED_SERVICES = new Set(["google-gmail", "google-sheets"]);

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

function getPayloadMessage(
  payload: {
    detail?: { message?: string } | string;
    message?: string;
  } | null,
  fallback: string
): string {
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  if (typeof payload?.message === "string") return payload.message;
  return fallback;
}

export default function ConnectionsPage() {
  const { user, loading: authLoading } = useAuth();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [connectingService, setConnectingService] = useState<string | null>(
    null
  );
  const [busyConnectionId, setBusyConnectionId] = useState<string | null>(null);
  const [expandedServices, setExpandedServices] = useState<Set<string>>(
    DEFAULT_EXPANDED_SERVICES
  );

  const connectedById = useMemo(
    () => new Map(connections.map((connection) => [connection.id, connection])),
    [connections]
  );
  const serviceByConnectionId = useMemo(
    () =>
      new Map(
        AVAILABLE_SERVICES.map((service) => [service.connectionId, service])
      ),
    []
  );
  const capabilitiesByServiceSlug = useMemo(
    () =>
      new Map(
        AVAILABLE_SERVICES.map((service) => [
          service.slug,
          GOOGLE_CAPABILITIES.filter(
            (capability) => capability.serviceSlug === service.slug
          ),
        ])
      ),
    []
  );

  const loadConnections = useCallback(async () => {
    if (!user) {
      setConnections([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch("/api/connections", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(
          await getErrorMessage(response, "Connections could not be loaded.")
        );
      }
      const data = (await response.json()) as { connections?: Connection[] };
      setConnections(data.connections ?? []);
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Connections could not be loaded."
      );
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (authLoading) return;
    void loadConnections();
  }, [authLoading, loadConnections]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const error = params.get("error");

    if (connected) {
      const serviceName =
        serviceByConnectionId.get(connected)?.name ?? "Google service";
      toast.success(`${serviceName} connected.`);
      void loadConnections();
    }
    if (error) {
      toast.error(error);
    }

    if (connected || error) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [loadConnections, serviceByConnectionId]);

  const startGoogleConnect = async (service: AvailableService) => {
    if (!user) {
      toast.error(`Please sign in before connecting ${service.name}.`);
      return;
    }

    setConnectingService(service.slug);
    try {
      const token = await user.getIdToken();
      const response = await fetch(service.authorizePath, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ return_to: "/dashboard/connections" }),
      });
      const payload = (await response.json().catch(() => null)) as {
        authorizationUrl?: string;
        detail?: { message?: string } | string;
        message?: string;
      } | null;
      if (!response.ok || !payload?.authorizationUrl) {
        throw new Error(getPayloadMessage(payload, "Could not start Google OAuth."));
      }
      window.location.href = payload.authorizationUrl;
    } catch (error) {
      setConnectingService(null);
      toast.error(
        error instanceof Error ? error.message : "Could not start Google OAuth."
      );
    }
  };

  const disconnectConnection = async (connection: Connection) => {
    if (!user) return;
    const confirmed = window.confirm(`Disconnect ${connection.serviceName}?`);
    if (!confirmed) return;

    setBusyConnectionId(connection.id);
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/connections/${encodeURIComponent(connection.id)}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) {
        throw new Error(
          await getErrorMessage(response, "Connection could not be removed.")
        );
      }
      setConnections((prev) =>
        prev.filter((existing) => existing.id !== connection.id)
      );
      toast.success(`${connection.serviceName} disconnected.`);
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Connection could not be removed."
      );
    } finally {
      setBusyConnectionId(null);
    }
  };

  const toggleService = (slug: string) => {
    setExpandedServices((current) => {
      const next = new Set(current);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  };

  return (
    <div>
      <h1 className="text-2xl font-medium text-foreground mb-6">Connections</h1>

      <section>
        <h2 className="text-[16px] font-medium text-foreground mb-3">
          Connected Services
        </h2>
        {isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : (
          <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2">
            {AVAILABLE_SERVICES.map((service) => {
              const connection = connectedById.get(service.connectionId);
              const isConnected = connection?.status === "connected";
              const isExpanded = expandedServices.has(service.slug);
              const isBusy = connectingService === service.slug;
              const serviceCapabilities =
                capabilitiesByServiceSlug.get(service.slug) ?? [];

              return (
                <Card key={service.slug}>
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-white">
                        <ServiceLogo service={`${service.name} ${service.icon}`} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-[14px] font-medium text-foreground">
                            {service.name}
                          </p>
                          <Badge variant={isConnected ? "success" : "warning"}>
                            {isConnected ? "Connected" : "Not connected"}
                          </Badge>
                        </div>
                        <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
                          {connection?.accountEmail ?? service.description}
                        </p>
                      </div>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 shrink-0"
                        onClick={() => toggleService(service.slug)}
                        aria-label={`${isExpanded ? "Hide" : "Show"} ${service.name} permissions`}
                        aria-expanded={isExpanded}
                      >
                        <ChevronDown
                          className={`h-4 w-4 transition-transform ${
                            isExpanded ? "rotate-180" : ""
                          }`}
                        />
                      </Button>
                    </div>

                    {isExpanded && (
                      <div className="mt-4 space-y-2 border-t border-border pt-3">
                        {serviceCapabilities.map((capability) => {
                          const granted =
                            isConnected &&
                            Boolean(
                              connection?.capabilities?.includes(capability.id)
                            );
                          return (
                            <div
                              key={capability.id}
                              className="flex min-h-[58px] items-center gap-3 rounded-lg border border-border bg-background px-3 py-2"
                            >
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                                {granted ? (
                                  <CheckCircle2 className="h-4 w-4 text-success" />
                                ) : (
                                  <ShieldCheck className="h-4 w-4" />
                                )}
                              </div>
                              <div className="min-w-0 flex-1">
                                <p className="text-[13px] font-medium text-foreground">
                                  {capability.label}
                                </p>
                                <p className="truncate text-[12px] text-muted-foreground">
                                  {capability.description}
                                </p>
                              </div>
                              {granted ? (
                                <Badge variant="success">Granted</Badge>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 shrink-0 px-2 text-[12px]"
                                  onClick={() => void startGoogleConnect(service)}
                                  disabled={isBusy}
                                >
                                  {isBusy ? (
                                    <>
                                      <Spinner
                                        size="sm"
                                        className="text-current"
                                      />
                                      Granting
                                    </>
                                  ) : (
                                    <>
                                      <Plus className="h-3 w-3" />
                                      Grant
                                    </>
                                  )}
                                </Button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    <div className="mt-3 flex items-center justify-end gap-2 border-t border-border pt-3">
                      {!isConnected && (
                        <Button
                          size="sm"
                          variant="default"
                          className="h-7 px-3 text-[12px]"
                          onClick={() => void startGoogleConnect(service)}
                          disabled={isBusy}
                        >
                          {isBusy ? (
                            <>
                              <Spinner size="sm" className="text-current" />
                              Connecting
                            </>
                          ) : (
                            <>
                              <Plug className="h-3 w-3" />
                              Connect
                            </>
                          )}
                        </Button>
                      )}
                      {isConnected && connection && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-3 text-[12px] text-muted-foreground hover:text-error"
                          onClick={() => void disconnectConnection(connection)}
                          disabled={busyConnectionId === connection.id}
                        >
                          Disconnect
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-[16px] font-medium text-foreground mb-3">
          Available Services
        </h2>
        <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2">
          {AVAILABLE_SERVICES.map((service) => {
            const existingConnection = connectedById.get(service.connectionId);
            const isBusy = connectingService === service.slug;

            return (
              <Card key={service.slug}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-white">
                      <ServiceLogo service={`${service.name} ${service.icon}`} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[14px] font-medium text-foreground">
                        {service.name}
                      </p>
                      <p className="truncate text-[12px] text-muted-foreground">
                        {service.description}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant={existingConnection ? "outline" : "default"}
                      className="h-7 shrink-0 px-3 text-[12px]"
                      onClick={() => void startGoogleConnect(service)}
                      disabled={isBusy}
                    >
                      {isBusy ? (
                        <>
                          <Spinner size="sm" className="text-current" />
                          Connecting
                        </>
                      ) : existingConnection ? (
                        <>
                          <Plus className="h-3 w-3" />
                          Grant
                        </>
                      ) : (
                        <>
                          <Plug className="h-3 w-3" />
                          Connect
                        </>
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
