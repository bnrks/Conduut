"use client";

import { useState } from "react";
import { CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export type OAuthStatus = "pending" | "connecting" | "connected";

export interface OAuthPromptData {
  service: string;
  description: string;
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
  const [status, setStatus] = useState<OAuthStatus>(initialStatus);

  const handleConnect = () => {
    setStatus("connecting");
    // Simulate connection flow
    setTimeout(() => setStatus("connected"), 1500);
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
          {status === "connected" ? "Connected successfully" : data.description}
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
