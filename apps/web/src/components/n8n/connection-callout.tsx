"use client";

import Link from "next/link";
import { AlertCircle, ArrowRight, Server } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface ConnectionCalloutProps {
  title?: string;
  description?: string;
  statusLabel?: string;
  compact?: boolean;
  className?: string;
}

export function ConnectionCallout({
  title = "Connect your automation server",
  description = "Conduut needs your n8n URL and API key before it can read workflows, run automations, or inspect run history.",
  statusLabel,
  compact = false,
  className,
}: ConnectionCalloutProps) {
  return (
    <Card className={cn("border-border bg-card", className)}>
      <CardContent className={cn("flex gap-3", compact ? "p-4" : "p-5")}>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-conduut-50">
          <Server className="h-5 w-5 text-conduut-500" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[15px] font-medium text-foreground">{title}</p>
            {statusLabel ? <Badge variant="outline">{statusLabel}</Badge> : null}
          </div>
          <p className="mt-1 text-[13px] leading-6 text-muted-foreground">{description}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Link href="/dashboard/settings?tab=automation-server">
              <Button size="sm" className="gap-1.5">
                Open settings
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </Link>
            <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <AlertCircle className="h-3.5 w-3.5" />
              API keys stay write-only and are never shown again.
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
