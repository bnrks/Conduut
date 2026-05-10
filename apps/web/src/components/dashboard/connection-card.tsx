import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ServiceLogo } from "@/components/dashboard/service-logo";
import type { Connection, ConnectionStatus } from "@/types/connection";

function statusBadgeVariant(
  status: ConnectionStatus
): "success" | "warning" | "error" {
  if (status === "connected") return "success";
  if (status === "expired") return "warning";
  return "error";
}

function statusLabel(status: ConnectionStatus): string {
  if (status === "connected") return "Connected";
  if (status === "expired") return "Expired";
  return "Error";
}

interface ConnectionCardProps {
  connection: Connection;
  onDisconnect?: (connection: Connection) => void;
  onReconnect?: (connection: Connection) => void;
  isBusy?: boolean;
}

export function ConnectionCard({
  connection,
  onDisconnect,
  onReconnect,
  isBusy = false,
}: ConnectionCardProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-white">
            <ServiceLogo
              service={`${connection.serviceName} ${connection.serviceIcon}`}
              className="h-6 w-6"
            />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-[14px] font-medium text-foreground">
                {connection.serviceName}
              </span>
              <Badge variant={statusBadgeVariant(connection.status)}>
                {statusLabel(connection.status)}
              </Badge>
            </div>
            {connection.accountEmail && (
              <p className="text-[12px] text-muted-foreground truncate">
                {connection.accountEmail}
              </p>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 mt-3 pt-3 border-t border-border">
          {connection.status === "expired" && (
            <Button
              size="sm"
              variant="default"
              className="h-7 text-[12px] px-3"
              onClick={() => onReconnect?.(connection)}
              disabled={isBusy}
            >
              Reconnect
            </Button>
          )}
          {connection.status === "connected" && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-[12px] px-3 text-muted-foreground hover:text-error"
              onClick={() => onDisconnect?.(connection)}
              disabled={isBusy}
            >
              Disconnect
            </Button>
          )}
          {connection.status === "error" && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[12px] px-3"
              onClick={() => onReconnect?.(connection)}
              disabled={isBusy}
            >
              Reconnect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
