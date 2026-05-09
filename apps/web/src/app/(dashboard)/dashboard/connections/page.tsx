"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Mail, Plus, RefreshCw, Table2 } from "lucide-react";
import { toast } from "sonner";
import { ConnectionCard } from "@/components/dashboard/connection-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import type { AvailableService, Connection } from "@/types/connection";
import { cn } from "@/lib/utils";

const AVAILABLE_SERVICES: AvailableService[] = [
  {
    name: "Google Gmail",
    slug: "google-gmail",
    icon: "google",
    description: "Read and send Gmail messages from workflows",
    category: "Email",
    connectionId: "google_gmail",
    authorizePath: "/api/connections/google/gmail/authorize",
  },
  {
    name: "Google Sheets",
    slug: "google-sheets",
    icon: "google",
    description: "Read spreadsheet rows from workflows",
    category: "Data",
    connectionId: "google_sheets",
    authorizePath: "/api/connections/google/sheets/authorize",
  },
];

const SERVICE_COLORS: Record<string, string> = {
  google: "bg-red-100 text-red-600",
};

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

export default function ConnectionsPage() {
  const { user, loading: authLoading } = useAuth();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [connectingService, setConnectingService] = useState<string | null>(
    null
  );
  const [busyConnectionId, setBusyConnectionId] = useState<string | null>(null);

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
        detail?: string;
        message?: string;
      } | null;
      if (!response.ok || !payload?.authorizationUrl) {
        throw new Error(
          payload?.detail ?? payload?.message ?? "Could not start Google OAuth."
        );
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

  return (
    <div>
      <h1 className="text-2xl font-medium text-foreground mb-6">Connections</h1>

      <section className="mb-8">
        <h2 className="text-[16px] font-medium text-foreground mb-3">
          Connected Services
        </h2>
        {isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : connections.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {connections.map((connection) => (
              <ConnectionCard
                key={connection.id}
                connection={connection}
                onDisconnect={(conn) => void disconnectConnection(conn)}
                onReconnect={(conn) => {
                  const service = serviceByConnectionId.get(conn.id);
                  if (service) void startGoogleConnect(service);
                }}
                isBusy={busyConnectionId === connection.id}
              />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="p-5 flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Mail className="h-5 w-5" />
              </div>
              <div>
                <p className="text-[14px] font-medium text-foreground">
                  No connected services
                </p>
                <p className="text-[13px] text-muted-foreground">
                  Connect Google services to run workflows.
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </section>

      <section>
        <h2 className="text-[16px] font-medium text-foreground mb-3">
          Available Services
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {AVAILABLE_SERVICES.map((service) => {
            const existingConnection = connectedById.get(service.connectionId);
            const colorClass =
              SERVICE_COLORS[service.icon] ?? "bg-conduut-50 text-conduut-700";
            const isBusy = connectingService === service.slug;
            const Icon = service.slug === "google-sheets" ? Table2 : Mail;

            return (
              <Card key={service.slug}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                        colorClass
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[14px] font-medium text-foreground">
                        {service.name}
                      </p>
                      <p className="text-[12px] text-muted-foreground truncate">
                        {service.description}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant={existingConnection ? "outline" : "default"}
                      className="h-7 text-[12px] px-3 shrink-0"
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
                          <RefreshCw className="h-3 w-3" />
                          Reconnect
                        </>
                      ) : (
                        <>
                          <Plus className="h-3 w-3" />
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
