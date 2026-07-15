"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  LoaderCircle,
  RefreshCw,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { setPendingExecutionRepair } from "@/lib/chat/pending-execution-repair";
import { cn } from "@/lib/utils";
import type {
  ExecutionDetail,
  ExecutionListResponse,
  ExecutionStatus,
  ExecutionSummary,
} from "@/types/execution";

const PAGE_SIZE = 25;

const STATUS_FILTERS: { label: string; value: "all" | ExecutionStatus }[] = [
  { label: "All statuses", value: "all" },
  { label: "Failed", value: "error" },
  { label: "Succeeded", value: "success" },
  { label: "Running", value: "running" },
  { label: "Waiting", value: "waiting" },
];

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string | { message?: string }; message?: string }
    | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  return payload?.message || fallback;
}

function formatDate(value: string | null): string {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null || durationMs < 0) return "—";
  if (durationMs < 1000) return `${durationMs} ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)} s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.floor((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function statusLabel(status: ExecutionStatus): string {
  if (status === "success") return "Succeeded";
  if (status === "error") return "Failed";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function StatusIcon({ status }: { status: ExecutionStatus }) {
  if (status === "success") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (status === "error") return <XCircle className="h-4 w-4 text-red-600" />;
  if (status === "running") return <LoaderCircle className="h-4 w-4 animate-spin text-blue-600" />;
  if (status === "waiting") return <Clock3 className="h-4 w-4 text-amber-600" />;
  return <AlertCircle className="h-4 w-4 text-muted-foreground" />;
}

function StatusBadge({ status }: { status: ExecutionStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium",
        status === "success" && "bg-emerald-50 text-emerald-700",
        status === "error" && "bg-red-50 text-red-700",
        status === "running" && "bg-blue-50 text-blue-700",
        status === "waiting" && "bg-amber-50 text-amber-700",
        !["success", "error", "running", "waiting"].includes(status) && "bg-muted text-muted-foreground"
      )}
    >
      <StatusIcon status={status} />
      {statusLabel(status)}
    </span>
  );
}

function RunDetailPanel({
  execution,
  loading,
  onClose,
  onFix,
}: {
  execution: ExecutionDetail | null;
  loading: boolean;
  onClose: () => void;
  onFix: (execution: ExecutionDetail) => void;
}) {
  return (
    <aside className="rounded-xl border border-border bg-card">
      <div className="flex items-start justify-between border-b border-border px-5 py-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Run details</p>
          <h2 className="mt-1 text-[15px] font-medium text-foreground">
            {execution ? `Execution ${execution.id}` : "Loading execution"}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Close run details"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading || !execution ? (
        <div className="flex justify-center py-20"><Spinner /></div>
      ) : (
        <div className="space-y-6 p-5">
          <div className="flex items-center justify-between gap-3">
            <StatusBadge status={execution.status} />
            <span className="text-[12px] text-muted-foreground">{execution.mode || "Unknown mode"}</span>
          </div>

          <dl className="grid gap-3 text-[13px]">
            <div>
              <dt className="text-muted-foreground">Workflow</dt>
              <dd className="mt-0.5 font-medium text-foreground">{execution.workflow_name || execution.workflow_id}</dd>
              {execution.workflow_name && <dd className="mt-0.5 text-[11px] text-muted-foreground">{execution.workflow_id}</dd>}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><dt className="text-muted-foreground">Started</dt><dd className="mt-0.5 text-foreground">{formatDate(execution.started_at)}</dd></div>
              <div><dt className="text-muted-foreground">Duration</dt><dd className="mt-0.5 text-foreground">{formatDuration(execution.duration_ms)}</dd></div>
            </div>
            {execution.finished_at && <div><dt className="text-muted-foreground">Finished</dt><dd className="mt-0.5 text-foreground">{formatDate(execution.finished_at)}</dd></div>}
          </dl>

          {execution.failed_node && (
            <div>
              <p className="text-[12px] font-medium text-muted-foreground">Failed step</p>
              <p className="mt-1 rounded-md bg-red-50 px-3 py-2 text-[13px] font-medium text-red-800">{execution.failed_node}</p>
            </div>
          )}

          {execution.error && (
            <div>
              <p className="text-[12px] font-medium text-muted-foreground">Error</p>
              <p className="mt-1 whitespace-pre-wrap break-words rounded-md border border-red-100 bg-red-50/60 px-3 py-2 text-[12px] leading-5 text-red-800">{execution.error}</p>
            </div>
          )}

          {execution.summary && (
            <div>
              <p className="text-[12px] font-medium text-muted-foreground">Summary</p>
              <p className="mt-1 whitespace-pre-wrap text-[13px] leading-5 text-foreground">{execution.summary}</p>
            </div>
          )}

          {execution.status === "error" && (
            <Button className="w-full gap-2" onClick={() => onFix(execution)}>
              <Wrench className="h-4 w-4" />
              Fix with Conduut
            </Button>
          )}
        </div>
      )}
    </aside>
  );
}

export default function RunsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [status, setStatus] = useState<"all" | ExecutionStatus>("all");
  const [workflowId, setWorkflowId] = useState("");
  const [appliedWorkflowId, setAppliedWorkflowId] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ExecutionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const listRequestId = useRef(0);
  const detailRequestId = useRef(0);

  const queryString = useMemo(() => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (status !== "all") params.set("status", status);
    if (appliedWorkflowId) params.set("workflow_id", appliedWorkflowId);
    return params.toString();
  }, [appliedWorkflowId, status]);

  const loadRuns = useCallback(async (cursor?: string) => {
    if (authLoading) return;
    if (!user) {
      listRequestId.current += 1;
      setExecutions([]);
      setLoading(false);
      setLoadingMore(false);
      return;
    }
    const requestId = ++listRequestId.current;
    if (cursor) setLoadingMore(true);
    else {
      setLoading(true);
      setLoadError(null);
    }
    try {
      const token = await user.getIdToken();
      const params = new URLSearchParams(queryString);
      if (cursor) params.set("cursor", cursor);
      const response = await fetch(`/api/executions?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(await responseMessage(response, "Runs could not be loaded."));
      const payload = (await response.json()) as ExecutionListResponse;
      if (requestId !== listRequestId.current) return;
      setExecutions((current) => cursor ? [...current, ...(payload.executions ?? [])] : (payload.executions ?? []));
      setNextCursor(payload.next_cursor ?? null);
    } catch (error) {
      if (requestId !== listRequestId.current) return;
      const message = error instanceof Error ? error.message : "Runs could not be loaded.";
      if (cursor) toast.error(message);
      else {
        setLoadError(message);
        setExecutions([]);
      }
    } finally {
      if (requestId === listRequestId.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [authLoading, queryString, user]);

  useEffect(() => { void loadRuns(); }, [loadRuns]);

  const openDetail = async (executionId: string) => {
    if (!user) return;
    const requestId = ++detailRequestId.current;
    setSelectedId(executionId);
    setDetail(null);
    setDetailLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/executions/${encodeURIComponent(executionId)}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(await responseMessage(response, "Run details could not be loaded."));
      const payload = (await response.json()) as ExecutionDetail;
      if (requestId !== detailRequestId.current) return;
      setDetail(payload);
    } catch (error) {
      if (requestId !== detailRequestId.current) return;
      toast.error(error instanceof Error ? error.message : "Run details could not be loaded.");
      setSelectedId(null);
    } finally {
      if (requestId === detailRequestId.current) setDetailLoading(false);
    }
  };

  const fixWithConduut = (execution: ExecutionDetail) => {
    setPendingExecutionRepair({
      execution_id: execution.id,
      intent: "diagnose_and_fix",
      workflow_name: execution.workflow_name || execution.workflow_id,
    });
    router.push("/chat");
  };

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-medium text-foreground">Runs</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">Inspect workflow execution history and troubleshoot failures.</p>
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" onClick={() => void loadRuns()} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <form
        className="mb-5 flex flex-col gap-3 rounded-lg border border-border bg-card p-3 sm:flex-row sm:items-end"
        onSubmit={(event) => { event.preventDefault(); setAppliedWorkflowId(workflowId.trim()); }}
      >
        <label className="flex-1 text-[12px] font-medium text-muted-foreground">
          Workflow ID
          <input
            value={workflowId}
            onChange={(event) => setWorkflowId(event.target.value)}
            placeholder="All workflows"
            className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] text-foreground outline-none focus:ring-2 focus:ring-ring"
          />
        </label>
        <label className="text-[12px] font-medium text-muted-foreground sm:w-48">
          Status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as "all" | ExecutionStatus)}
            className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] text-foreground outline-none focus:ring-2 focus:ring-ring"
          >
            {STATUS_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
          </select>
        </label>
        <Button type="submit" size="sm">Apply</Button>
        {(appliedWorkflowId || status !== "all") && (
          <Button type="button" variant="ghost" size="sm" onClick={() => { setWorkflowId(""); setAppliedWorkflowId(""); setStatus("all"); }}>Clear</Button>
        )}
      </form>

      <div className={cn("grid gap-5", selectedId && "xl:grid-cols-[minmax(0,1fr)_380px]")}>
        <section className="min-w-0 overflow-hidden rounded-xl border border-border bg-card">
          {loading ? (
            <div className="flex justify-center py-24"><Spinner /></div>
          ) : loadError ? (
            <div className="flex flex-col items-center px-6 py-20 text-center">
              <AlertCircle className="h-8 w-8 text-red-500" />
              <h2 className="mt-3 text-[15px] font-medium text-foreground">Runs could not be loaded</h2>
              <p className="mt-1 max-w-md text-[13px] text-muted-foreground">{loadError}</p>
              <Button variant="outline" size="sm" className="mt-5" onClick={() => void loadRuns()}>Try again</Button>
            </div>
          ) : executions.length === 0 ? (
            <div className="flex flex-col items-center px-6 py-20 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted"><Activity className="h-7 w-7 text-muted-foreground" /></div>
              <h2 className="mt-4 text-[15px] font-medium text-foreground">No runs found</h2>
              <p className="mt-1 max-w-sm text-[13px] text-muted-foreground">Run a workflow or change the filters to see execution history.</p>
            </div>
          ) : (
            <>
              <div className="hidden grid-cols-[minmax(0,1.5fr)_110px_150px_90px_28px] gap-4 border-b border-border bg-muted/30 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground md:grid">
                <span>Workflow</span><span>Status</span><span>Started</span><span>Duration</span><span />
              </div>
              <div className="divide-y divide-border">
                {executions.map((execution) => (
                  <button
                    key={execution.id}
                    type="button"
                    onClick={() => void openDetail(execution.id)}
                    className={cn(
                      "grid w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 md:grid-cols-[minmax(0,1.5fr)_110px_150px_90px_28px] md:items-center md:gap-4",
                      selectedId === execution.id && "bg-muted/60"
                    )}
                  >
                    <div className="min-w-0"><p className="truncate text-[13px] font-medium text-foreground">{execution.workflow_name || execution.workflow_id}</p><p className="mt-0.5 truncate text-[11px] text-muted-foreground">Execution {execution.id}{execution.mode ? ` · ${execution.mode}` : ""}</p></div>
                    <div><StatusBadge status={execution.status} /></div>
                    <span className="text-[12px] text-muted-foreground">{formatDate(execution.started_at)}</span>
                    <span className="text-[12px] text-muted-foreground">{formatDuration(execution.duration_ms)}</span>
                    <ChevronRight className="hidden h-4 w-4 text-muted-foreground md:block" />
                  </button>
                ))}
              </div>
              {nextCursor && (
                <div className="flex justify-center border-t border-border px-4 py-4">
                  <Button variant="outline" size="sm" disabled={loadingMore} onClick={() => void loadRuns(nextCursor)}>
                    {loadingMore && <LoaderCircle className="h-3.5 w-3.5 animate-spin" />}
                    Load more
                  </Button>
                </div>
              )}
            </>
          )}
        </section>

        {selectedId && <RunDetailPanel execution={detail} loading={detailLoading} onClose={() => { detailRequestId.current += 1; setSelectedId(null); setDetail(null); setDetailLoading(false); }} onFix={fixWithConduut} />}
      </div>
    </div>
  );
}
