"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Bot,
  Braces,
  DatabaseZap,
  RefreshCw,
  Sparkles,
  Wrench,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";
import type { TokenUsageTotals, UsageSummaryResponse } from "@/types/usage";

const PERIODS = [
  { days: 1, label: "Last 24 hours" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
] as const;

const EMPTY_TOTALS: TokenUsageTotals = {
  agent_runs: 0,
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  model_requests: 0,
  tool_calls: 0,
};

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string | { message?: string }; message?: string }
    | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  return payload?.message || fallback;
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function shortDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function UsageCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: number;
  detail: string;
  icon: typeof Sparkles;
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <span className="text-[13px] text-muted-foreground">{label}</span>
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-conduut-50">
            <Icon className="h-4 w-4 text-conduut-500" />
          </span>
        </div>
        <p className="text-2xl font-medium tabular-nums text-foreground">{formatNumber(value)}</p>
        <p className="mt-1 text-[12px] text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

export function UsageDashboard() {
  const { user, loading: authLoading } = useAuth();
  const [days, setDays] = useState<1 | 7 | 30 | 90>(30);
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const loadUsage = useCallback(async () => {
    if (authLoading) return;
    if (!user) {
      requestId.current += 1;
      setSummary(null);
      setLoading(false);
      return;
    }

    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/usage?days=${days}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(await responseMessage(response, "Token usage could not be loaded."));
      }
      const payload = (await response.json()) as UsageSummaryResponse;
      if (requestId.current === currentRequest) setSummary(payload);
    } catch (loadError) {
      if (requestId.current !== currentRequest) return;
      setSummary(null);
      setError(loadError instanceof Error ? loadError.message : "Token usage could not be loaded.");
    } finally {
      if (requestId.current === currentRequest) setLoading(false);
    }
  }, [authLoading, days, user]);

  useEffect(() => {
    void loadUsage();
  }, [loadUsage]);

  const totals = summary?.totals ?? EMPTY_TOTALS;
  const chart = useMemo(() => {
    const points = summary?.daily ?? [];
    const max = Math.max(1, ...points.map((point) => point.total_tokens));
    return { points, max };
  }, [summary]);

  return (
    <div>
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-medium text-foreground">Usage</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Token usage from completed Conduut agent runs.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-border bg-card p-1">
            {PERIODS.map((period) => (
              <button
                key={period.days}
                type="button"
                onClick={() => setDays(period.days)}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors",
                  days === period.days
                    ? "bg-conduut-50 text-conduut-700"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {period.label}
              </button>
            ))}
          </div>
          <Button variant="outline" size="sm" onClick={() => void loadUsage()} disabled={loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {loading && !summary ? (
        <div className="flex min-h-80 items-center justify-center rounded-xl border border-border bg-card">
          <Spinner />
        </div>
      ) : error ? (
        <div className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-border bg-card px-6 text-center">
          <DatabaseZap className="h-8 w-8 text-red-500" />
          <h2 className="mt-3 text-[15px] font-medium text-foreground">Usage could not be loaded</h2>
          <p className="mt-1 max-w-md text-[13px] text-muted-foreground">{error}</p>
          <Button variant="outline" size="sm" className="mt-5" onClick={() => void loadUsage()}>
            Try again
          </Button>
        </div>
      ) : (
        <>
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <UsageCard label="Recorded tokens" value={totals.total_tokens} detail="Completed runs · input + output" icon={Sparkles} />
            <UsageCard label="Input tokens" value={totals.input_tokens} detail="Prompt and context" icon={ArrowDownToLine} />
            <UsageCard label="Output tokens" value={totals.output_tokens} detail="Model responses" icon={ArrowUpFromLine} />
            <UsageCard label="Agent runs" value={totals.agent_runs} detail="Completed responses" icon={Bot} />
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.6fr)]">
            <Card>
              <CardHeader>
                <div>
                  <h2 className="text-[15px] font-medium text-foreground">Token trend</h2>
                  <p className="mt-1 text-[12px] text-muted-foreground">Rolling window grouped by UTC day; edge days may be partial.</p>
                </div>
              </CardHeader>
              <CardContent>
                {totals.agent_runs === 0 ? (
                  <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-6 text-center">
                    <Braces className="h-7 w-7 text-muted-foreground" />
                    <p className="mt-3 text-[13px] font-medium text-foreground">No recorded usage yet</p>
                    <p className="mt-1 text-[12px] text-muted-foreground">
                      Completed agent runs will appear here after this tracking update.
                    </p>
                  </div>
                ) : (
                  <div className="overflow-x-auto pb-1">
                    <div className="flex h-52 min-w-[560px] items-end gap-1.5">
                      {chart.points.map((point) => {
                        const height = point.total_tokens === 0 ? 2 : Math.max(6, (point.total_tokens / chart.max) * 100);
                        return (
                          <div key={point.date} className="group flex h-full min-w-1 flex-1 flex-col justify-end">
                            <div className="relative flex flex-1 items-end">
                              <div
                                className="w-full rounded-t bg-conduut-300 transition-colors group-hover:bg-conduut-500"
                                style={{ height: `${height}%` }}
                                title={`${shortDate(point.date)}: ${formatNumber(point.total_tokens)} tokens`}
                              />
                            </div>
                            <span className="mt-2 truncate text-center text-[9px] text-muted-foreground">
                              {chart.points.length <= 10 || point === chart.points[0] || point === chart.points.at(-1)
                                ? shortDate(point.date)
                                : ""}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <h2 className="text-[15px] font-medium text-foreground">Run details</h2>
              </CardHeader>
              <CardContent className="space-y-4">
                {[
                  ["Cache read", totals.cache_read_tokens, DatabaseZap],
                  ["Cache write", totals.cache_write_tokens, DatabaseZap],
                  ["Model requests", totals.model_requests, RefreshCw],
                  ["Tool calls", totals.tool_calls, Wrench],
                ].map(([label, value, Icon]) => {
                  const DetailIcon = Icon as typeof Sparkles;
                  return (
                    <div key={String(label)} className="flex items-center justify-between gap-4 border-b border-border pb-4 last:border-0 last:pb-0">
                      <span className="flex items-center gap-2 text-[13px] text-muted-foreground">
                        <DetailIcon className="h-3.5 w-3.5" />
                        {String(label)}
                      </span>
                      <span className="text-[13px] font-medium tabular-nums text-foreground">{formatNumber(Number(value))}</span>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          </div>

          <p className="mt-4 text-[11px] leading-5 text-muted-foreground">
            Tracking starts with this update. Totals include completed agent responses only; router calls, failed attempts, and cancelled runs are not included yet. Cache counters are shown separately and are not added to total tokens.
          </p>
        </>
      )}
    </div>
  );
}
