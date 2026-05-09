"use client";

import { useState } from "react";
import { CheckCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

export type OAuthStatus = "pending" | "connecting" | "connected" | "error";

export interface OAuthPromptData {
  service: string;
  description: string;
  authorizePath?: string;
  returnTo?: string;
  iconUrl?: string;
}

export interface OAuthPromptProps {
  data: OAuthPromptData;
  initialStatus?: OAuthStatus;
  className?: string;
}

const SERVICE_INITIALS: Record<string, string> = {
  github: "GH",
  google: "G",
  slack: "SL",
  notion: "N",
  discord: "DC",
  telegram: "TG",
  airtable: "AT",
};

export function OAuthPrompt({
  data,
  initialStatus = "pending",
  className,
}: OAuthPromptProps) {
  const { user } = useAuth();
  const [status, setStatus] = useState<OAuthStatus>(initialStatus);

  const handleConnect = async () => {
    if (!user) {
      toast.error("Please sign in before connecting Google Gmail.");
      return;
    }

    setStatus("connecting");
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        data.authorizePath ?? "/api/connections/google/gmail/authorize",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            return_to: data.returnTo ?? window.location.pathname,
          }),
        }
      );
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
      setStatus("error");
      toast.error(
        error instanceof Error ? error.message : "Could not start Google OAuth."
      );
    }
  };

  const initials =
    SERVICE_INITIALS[data.service.toLowerCase()] ??
    data.service.slice(0, 2).toUpperCase();

  return (
    <div
      className={cn(
        "border border-border rounded-lg p-3 flex items-center gap-3 bg-conduut-50 mt-2",
        status === "connected" && "bg-success-light border-success/20",
        className
      )}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white border border-border text-[12px] font-medium text-foreground">
        {initials}
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-medium text-[14px] text-foreground">{data.service}</p>
        <p className="text-[12px] text-muted-foreground truncate">
          {status === "connected"
            ? "Connected successfully"
            : status === "error"
              ? "Connection could not be started"
              : data.description}
        </p>
      </div>
      <div className="shrink-0">
        {status === "connected" ? (
          <CheckCircle className="h-5 w-5 text-success" />
        ) : (
          <Button
            size="sm"
            variant="default"
            onClick={handleConnect}
            disabled={status === "connecting"}
            className="h-8 px-3 text-[13px]"
          >
            {status === "connecting" ? (
              <>
                <Spinner size="sm" className="text-white" />
                Connecting
              </>
            ) : (
              "Connect"
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
