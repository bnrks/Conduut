"use client";

import type { ChangeEvent, FormEvent } from "react";
import { Fragment, useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Activity,
  CheckCircle2,
  CheckSquare,
  ChevronRight,
  Plus,
  Search,
  Table2,
  Upload,
  Workflow as WorkflowIcon,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { ArtifactPreview } from "@/components/artifacts/artifact-preview";
import { ConnectionCallout } from "@/components/n8n/connection-callout";
import { WorkflowResultView } from "@/components/dashboard/workflow-result-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { WorkflowCard } from "@/components/dashboard/workflow-card";
import { BulkActionBar } from "@/components/dashboard/bulk-action-bar";
import { WorkflowRunningOverlay } from "@/components/dashboard/workflow-running-overlay";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useMultiSelect } from "@/hooks/use-multi-select";
import { useAuth } from "@/hooks/use-auth";
import { useN8nInstance } from "@/hooks/use-n8n-instance";
import type { ArtifactPreviewData } from "@/types/artifact";
import type { Workflow, WorkflowInputField, WorkflowResultPresentation, WorkflowStatus } from "@/types/workflow";

type StatusFilter = "all" | WorkflowStatus;
type RunMode = "single" | "batch";
type BatchSource = "file" | "manual";
type BatchMappingSource = "column" | "fixed" | "none";
type WorkflowFunctionalStatus =
  | "verified"
  | "no_action"
  | "partial"
  | "needs_attention"
  | "failed"
  | "unknown"
  | "unverified";

interface WorkflowAssessmentWarning {
  code?: string;
  severity?: string;
  node_name?: string;
  message?: string;
}

interface WorkflowAssessmentEvidence {
  kind?: string;
  node_name?: string;
  item_count?: number;
  receipt_count?: number;
  nodeName?: string;
  itemCount?: number;
  receiptCount?: number;
}

interface WorkflowRunAssessment {
  transport_ok?: boolean;
  execution_ok?: boolean;
  coverage?: "full" | "partial" | "none";
  eligible_count?: number;
  action_count?: number;
  writeback_count?: number;
  postconditions_verified?: number | boolean;
  duplicate_risk?: boolean;
  warnings?: (WorkflowAssessmentWarning | string)[];
  evidence?: WorkflowAssessmentEvidence[];
  // Legacy camelCase assessment fields kept for in-flight/older SSE payloads.
  transportStatusCode?: number;
  configuredMutationNodes?: string[];
  executedMutationNodes?: string[];
  successfulMutationNodes?: string[];
  zeroOutputMutationNodes?: string[];
  runDataHints?: {
    nodeName?: string;
    outputItemCount?: number;
    runStatus?: string;
    hasError?: boolean;
  }[];
  reasons?: string[];
  transportOk?: boolean;
  executionOk?: boolean;
  eligibleCount?: number;
  actionCount?: number;
  writebackCount?: number;
  postconditionsVerified?: number | boolean;
  duplicateRisk?: boolean;
}

interface WorkflowRunOutput {
  nodeName: string;
  itemCount: number;
  items: unknown[];
}

interface WorkflowRunResult {
  workflowName: string;
  executionId?: string;
  status?: string;
  functionalStatus?: WorkflowFunctionalStatus;
  assessment?: WorkflowRunAssessment;
  claimableOutcome?: unknown;
  summary?: string;
  failedNode?: string;
  error?: string;
  outputs?: WorkflowRunOutput[];
  artifacts?: ArtifactPreviewData[];
  presentation?: WorkflowResultPresentation | null;
}

interface ParsedWorkbook {
  fileName: string;
  sheetNames: string[];
  sheets: Record<string, unknown[][]>;
}

interface BatchMapping {
  source: BatchMappingSource;
  columnIndex?: number;
  fixedValue?: string;
}

interface BatchRunRowResult {
  rowNumber: number;
  status: string;
  execution_id?: string;
  functional_status?: WorkflowFunctionalStatus;
  functionalStatus?: WorkflowFunctionalStatus;
  assessment?: WorkflowRunAssessment;
  claimable_outcome?: unknown;
  claimableOutcome?: unknown;
  summary?: string;
  error?: string;
  outputs?: WorkflowRunOutput[];
  artifacts?: ArtifactPreviewData[];
  presentation?: WorkflowResultPresentation | null;
}

interface WorkflowBatchRunResult {
  workflowName: string;
  status: string;
  functional_status?: WorkflowFunctionalStatus;
  functionalStatus?: WorkflowFunctionalStatus;
  assessment?: WorkflowRunAssessment;
  claimable_outcome?: unknown;
  claimableOutcome?: unknown;
  totalRows: number;
  succeeded: number;
  failed: number;
  skipped: number;
  verified?: number;
  no_action?: number;
  noAction?: number;
  partial?: number;
  needs_attention?: number;
  needsAttention?: number;
  unknown?: number;
  results: BatchRunRowResult[];
}

interface BatchRunRowPayload {
  rowNumber: number;
  input: Record<string, string>;
}

interface BatchRowPreview {
  rowNumber: number;
  fields: { label: string; value: string }[];
}

interface BatchRunProgress {
  workflowId: string;
  workflowName: string;
  totalRows: number;
  completedRows: number;
  currentIndex: number;
  currentRowNumber?: number;
  currentPreview?: BatchRowPreview;
  succeeded: number;
  failed: number;
  skipped: number;
  error?: string;
}

interface BatchStreamEvent {
  event: string;
  data: Record<string, unknown>;
}

const MAX_BATCH_ROWS = 50;
const MIN_OVERLAY_MS = 700;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Overlay'i en az MIN_OVERLAY_MS görünür tutar — çok hızlı dönen run'larda
// "yanıp sönme"yi engeller.
async function ensureMinOverlay(startedAt: number): Promise<void> {
  const elapsed = performance.now() - startedAt;
  if (elapsed < MIN_OVERLAY_MS) {
    await delay(MIN_OVERLAY_MS - elapsed);
  }
}

async function getErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => null) as {
    detail?: { message?: string } | string;
    message?: string;
  } | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  if (typeof payload?.message === "string") return payload.message;
  return fallback;
}

function cellText(value: unknown): string {
  if (value == null) return "";
  return String(value).trim();
}

function isEmptyRow(row: unknown[] | undefined): boolean {
  return !row || row.every((value) => cellText(value) === "");
}

function normalizedLabel(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function columnLabel(headers: string[], index: number): string {
  return headers[index] || `Column ${index + 1}`;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
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

function readBoolean(record: Record<string, unknown> | null, ...keys: string[]): boolean | undefined {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "boolean") return value;
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

function normalizeWorkflow(raw: unknown): Workflow {
  const record = asRecord(raw);
  const status = readString(record, "status") === "active" ? "active" : "inactive";
  const source =
    readString(record, "source", "origin", "management_mode", "managementMode", "ownership") ??
    "conduut";
  const readOnly =
    readBoolean(record, "read_only", "readOnly") ??
    ["external", "remote", "unmanaged"].includes(source);

  return {
    id: readString(record, "id") ?? crypto.randomUUID(),
    name: readString(record, "name") ?? "Untitled workflow",
    description: readString(record, "description"),
    status,
    nodeCount: readNumber(record, "nodeCount", "node_count") ?? 0,
    lastExecutionAt: readString(record, "lastExecutionAt", "last_execution_at"),
    executionCount: readNumber(record, "executionCount", "execution_count") ?? 0,
    createdAt: readString(record, "createdAt", "created_at") ?? "",
    updatedAt: readString(record, "updatedAt", "updated_at") ?? "",
    inputSchema: Array.isArray(record?.inputSchema)
      ? (record.inputSchema as WorkflowInputField[])
      : Array.isArray(record?.input_schema)
        ? (record.input_schema as WorkflowInputField[])
        : undefined,
    source,
    origin: readString(record, "origin"),
    managementMode: readString(record, "management_mode", "managementMode"),
    readOnly,
    adoptable: readBoolean(record, "adoptable") ?? readOnly,
    instanceId: readString(record, "instance_id", "instanceId"),
  };
}

function isReadOnlyWorkflow(workflow: Workflow): boolean {
  return workflow.readOnly === true;
}

function parseSseEvent(raw: string): BatchStreamEvent | null {
  const lines = raw.replaceAll("\r", "").split("\n");
  let event = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      data += line.slice(5).trimStart();
    }
  }

  if (!data) return null;

  try {
    return { event, data: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return null;
  }
}

async function streamWorkflowBatchRun({
  token,
  workflowId,
  rows,
  previewToken,
  onEvent,
}: {
  token: string;
  workflowId: string;
  rows: BatchRunRowPayload[];
  previewToken?: string;
  onEvent: (event: BatchStreamEvent) => void;
}): Promise<void> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(workflowId)}?action=batch-run-stream`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        source: "dashboard",
        rows,
        previewToken,
        options: { continueOnError: true },
      }),
    }
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response, "Could not run workflow batch."));
  }
  if (!response.body) {
    throw new Error("Batch progress stream could not be opened.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushEvents = () => {
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseEvent(rawEvent);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      flushEvents();
    }
    buffer += decoder.decode();
    if (buffer.trim().length > 0) {
      const parsed = parseSseEvent(buffer);
      if (parsed) onEvent(parsed);
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* noop */
    }
  }
}

function BatchRunProgressDialog({
  progress,
  onClose,
}: {
  progress: BatchRunProgress;
  onClose: () => void;
}) {
  const isErrored = Boolean(progress.error);
  const percent =
    progress.totalRows > 0
      ? Math.min(100, Math.round((progress.completedRows / progress.totalRows) * 100))
      : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="workflow-batch-progress-title"
      onClick={() => {
        if (isErrored) onClose();
      }}
    >
      <div
        className="w-full max-w-xl rounded-lg border border-border bg-card p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2">
              {isErrored ? (
                <XCircle className="h-5 w-5 text-error" />
              ) : (
                <span className="relative flex h-5 w-5 items-center justify-center">
                  <span className="absolute h-5 w-5 animate-ping rounded-full bg-conduut-500/20" />
                  <Activity className="relative h-5 w-5 text-conduut-500" />
                </span>
              )}
              <h2
                id="workflow-batch-progress-title"
                className="truncate text-[16px] font-medium text-foreground"
              >
                {progress.workflowName}
              </h2>
            </div>
            <p className="text-[13px] text-muted-foreground">
              {isErrored
                ? progress.error
                : `${Math.max(progress.currentIndex, progress.completedRows)} / ${progress.totalRows} running`}
            </p>
          </div>
          {isErrored ? (
            <Button size="sm" variant="outline" onClick={onClose}>
              Close
            </Button>
          ) : (
            <Spinner size="sm" className="mt-1 shrink-0" />
          )}
        </div>

        <div className="mb-5">
          <div className="mb-2 flex items-center justify-between text-[12px] text-muted-foreground">
            <span>{progress.completedRows} completed</span>
            <span>{percent}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-conduut-500 transition-all duration-300"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>

        <div className="mb-5 grid grid-cols-3 gap-2">
          <div className="rounded-md border border-border px-3 py-2">
            <p className="text-[11px] uppercase text-muted-foreground">Executed</p>
            <p className="mt-1 flex items-center gap-1.5 text-[15px] font-medium text-foreground">
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
              {progress.succeeded}
            </p>
          </div>
          <div className="rounded-md border border-border px-3 py-2">
            <p className="text-[11px] uppercase text-muted-foreground">Failed</p>
            <p className="mt-1 flex items-center gap-1.5 text-[15px] font-medium text-foreground">
              <XCircle className="h-4 w-4 text-error" />
              {progress.failed}
            </p>
          </div>
          <div className="rounded-md border border-border px-3 py-2">
            <p className="text-[11px] uppercase text-muted-foreground">Skipped</p>
            <p className="mt-1 text-[15px] font-medium text-foreground">{progress.skipped}</p>
          </div>
        </div>

        <div className="rounded-md border border-border bg-muted/30 px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-foreground">Current row</p>
            <span className="text-[12px] text-muted-foreground">
              {progress.currentRowNumber ? `Row ${progress.currentRowNumber}` : "Preparing"}
            </span>
          </div>
          {progress.currentPreview?.fields.length ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {progress.currentPreview.fields.map((field) => (
                <div key={field.label} className="min-w-0">
                  <p className="truncate text-[12px] text-muted-foreground">{field.label}</p>
                  <p className="truncate text-[13px] text-foreground">{field.value || "-"}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[13px] text-muted-foreground">Waiting for the first row.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// Run once ve batch (genişletilmiş satır) sonuçlarında ortak "ham veriyi gör"
// bloğu — n8n node çıktılarını JSON olarak açılır-kapanır gösterir.
function RunOutputsDetails({ outputs }: { outputs: WorkflowRunOutput[] }) {
  if (!outputs.length) return null;
  return (
    <details className="rounded-md border border-border bg-muted/30">
      <summary className="cursor-pointer px-3 py-2 text-[12px] font-medium text-muted-foreground">
        Ham veriyi gör
      </summary>
      <div className="flex flex-col gap-2 px-3 pb-3">
        {outputs.map((output, index) => (
          <div key={`out-${index}`} className="rounded-md border border-border bg-background p-3">
            <p className="mb-1.5 text-[12px] font-medium text-muted-foreground">
              {output.nodeName}
              {output.itemCount > 1 ? ` · ${output.itemCount} items` : ""}
            </p>
            <pre className="overflow-x-auto whitespace-pre-wrap break-words text-[12.5px] text-foreground">
              {JSON.stringify(output.items, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </details>
  );
}

function functionalStatusMeta(status: WorkflowFunctionalStatus) {
  switch (status) {
    case "verified":
      return { label: "Verified", variant: "success" as const };
    case "no_action":
      return { label: "No action needed", variant: "success" as const };
    case "partial":
      return { label: "Partially verified", variant: "warning" as const };
    case "needs_attention":
      return { label: "Needs attention", variant: "warning" as const };
    case "failed":
      return { label: "Failed", variant: "error" as const };
    case "unknown":
      return { label: "Verification unknown", variant: "warning" as const };
    case "unverified":
      return { label: "Unverified", variant: "warning" as const };
  }
}

function FunctionalStatusBadge({ status }: { status?: WorkflowFunctionalStatus }) {
  if (!status) return null;
  const meta = functionalStatusMeta(status);
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}

function BatchFunctionalCounts({ result }: { result: WorkflowBatchRunResult }) {
  const counts: [string, number | undefined, "success" | "warning"][] = [
    ["Verified", result.verified, "success"],
    ["No action", result.no_action ?? result.noAction, "success"],
    ["Partial", result.partial, "warning"],
    ["Needs attention", result.needs_attention ?? result.needsAttention, "warning"],
    ["Unknown", result.unknown, "warning"],
  ];
  const visible = counts.filter((entry): entry is [string, number, "success" | "warning"] =>
    Boolean(entry[1])
  );
  if (!visible.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {visible.map(([label, count, variant]) => (
        <Badge key={label} variant={variant}>
          {count} {label.toLowerCase()}
        </Badge>
      ))}
    </div>
  );
}

function assessmentValue(value: number | boolean): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function claimableOutcomeText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  return null;
}

function AssessmentDetails({
  assessment,
  claimableOutcome,
}: {
  assessment?: WorkflowRunAssessment;
  claimableOutcome?: unknown;
}) {
  const outcome = claimableOutcomeText(claimableOutcome);
  if (!assessment && !outcome) return null;

  const metrics = assessment
    ? [
        [
          "Eligible",
          assessment.eligible_count ??
            assessment.eligibleCount ??
            assessment.configuredMutationNodes?.length,
        ],
        [
          "Actions",
          assessment.action_count ??
            assessment.actionCount ??
            assessment.executedMutationNodes?.length,
        ],
        [
          "Write-backs",
          assessment.writeback_count ??
            assessment.writebackCount ??
            assessment.successfulMutationNodes?.length,
        ],
        [
          "Postconditions",
          assessment.postconditions_verified ?? assessment.postconditionsVerified,
        ],
      ].filter((entry): entry is [string, number | boolean] => entry[1] !== undefined)
    : [];
  const evidence: WorkflowAssessmentEvidence[] =
    assessment?.evidence ??
    (assessment?.runDataHints ?? []).map(
      (hint): WorkflowAssessmentEvidence => ({
        kind: hint.runStatus || (hint.hasError ? "error" : "run data"),
        node_name: hint.nodeName,
        item_count: hint.outputItemCount,
      })
    );
  const warnings = assessment?.warnings ?? [];
  const reasons = assessment?.reasons ?? [];

  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
        <span className="font-medium text-foreground">Assessment</span>
        {assessment?.coverage && <span>Coverage: {assessment.coverage}</span>}
        {assessment?.transport_ok !== undefined || assessment?.transportOk !== undefined ? (
          <span>
            Transport: {(assessment.transport_ok ?? assessment.transportOk) ? "ok" : "failed"}
          </span>
        ) : assessment?.transportStatusCode !== undefined ? (
          <span>Transport: HTTP {assessment.transportStatusCode}</span>
        ) : null}
        {(assessment?.execution_ok !== undefined || assessment?.executionOk !== undefined) && (
          <span>
            Execution: {(assessment.execution_ok ?? assessment.executionOk) ? "ok" : "failed"}
          </span>
        )}
        {(assessment?.duplicate_risk || assessment?.duplicateRisk) && (
          <span className="font-medium text-warning">Duplicate risk</span>
        )}
      </div>
      {outcome && (
        <p className="mt-2 text-[13px] text-foreground">
          Claimable outcome: {outcome.replaceAll("_", " ")}
        </p>
      )}
      {metrics.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {metrics.map(([label, value]) => (
            <span
              key={label}
              className="rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground"
            >
              {label}: {assessmentValue(value)}
            </span>
          ))}
        </div>
      )}
      {evidence.length > 0 && (
        <div className="mt-2 space-y-1">
          {evidence.map((item, index) => (
            <p key={`${item.kind ?? "evidence"}-${index}`} className="text-[12px] text-muted-foreground">
              <span className="font-medium text-foreground">{item.kind || "Evidence"}</span>
              {item.node_name || item.nodeName ? ` · ${item.node_name ?? item.nodeName}` : ""}
              {item.item_count !== undefined || item.itemCount !== undefined
                ? ` · ${item.item_count ?? item.itemCount} items`
                : ""}
              {item.receipt_count !== undefined || item.receiptCount !== undefined
                ? ` · ${item.receipt_count ?? item.receiptCount} receipts`
                : ""}
            </p>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <div className="mt-2 space-y-1">
          {warnings.map((warning, index) => {
            const warningData = typeof warning === "string" ? null : warning;
            const message = typeof warning === "string" ? warning : warning.message || warning.code;
            return (
              <p
                key={`${warningData?.code ?? message ?? "warning"}-${index}`}
                className={`text-[12px] ${
                  warningData?.severity === "error" ? "text-error" : "text-warning"
                }`}
              >
                {warningData?.node_name ? `${warningData.node_name}: ` : ""}
                {message || "Assessment warning"}
              </p>
            );
          })}
        </div>
      )}
      {reasons.length > 0 && (
        <div className="mt-2 space-y-1">
          {reasons.map((reason, index) => (
            <p key={`${reason}-${index}`} className="text-[12px] text-muted-foreground">
              {reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function aggregateFunctionalStatus(
  result: Omit<WorkflowBatchRunResult, "workflowName">
): WorkflowFunctionalStatus | undefined {
  if (result.functional_status || result.functionalStatus) {
    return result.functional_status ?? result.functionalStatus;
  }
  const statuses = result.results
    .map((row) => row.functional_status ?? row.functionalStatus)
    .filter((status): status is WorkflowFunctionalStatus => Boolean(status));
  if (!statuses.length) return undefined;
  if (statuses.includes("failed")) return "failed";
  if (statuses.includes("needs_attention")) return "needs_attention";
  if (statuses.includes("partial")) return "partial";
  if (statuses.includes("unknown")) return "unknown";
  if (statuses.includes("unverified")) return "unverified";
  if (statuses.every((status) => status === "no_action")) return "no_action";
  return "verified";
}

function notifyFunctionalResult(
  functionalStatus: WorkflowFunctionalStatus | undefined,
  message: string,
  fallbackFailed: boolean
) {
  if (!functionalStatus) {
    if (fallbackFailed) toast.error(message);
    else toast.success(message);
    return;
  }
  if (fallbackFailed || functionalStatus === "failed") {
    toast.error(message);
    return;
  }
  if (functionalStatus === "verified" || functionalStatus === "no_action") {
    toast.success(message);
    return;
  }
  toast.warning(message);
}

export default function WorkflowsPage() {
  const { user, loading: authLoading } = useAuth();
  const {
    instance,
    loading: instanceLoading,
    error: instanceError,
    connected: instanceConnected,
    connectionRequired,
    refresh: refreshInstance,
  } = useN8nInstance();
  const confirm = useConfirm();
  const selection = useMultiSelect();
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [runWorkflow, setRunWorkflow] = useState<Workflow | null>(null);
  const [runMode, setRunMode] = useState<RunMode>("single");
  const [runValues, setRunValues] = useState<Record<string, string>>({});
  const [parsedWorkbook, setParsedWorkbook] = useState<ParsedWorkbook | null>(null);
  const [selectedSheet, setSelectedSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [dataStartRow, setDataStartRow] = useState(2);
  const [dataEndRow, setDataEndRow] = useState(2);
  const [batchMappings, setBatchMappings] = useState<Record<string, BatchMapping>>({});
  const [batchSource, setBatchSource] = useState<BatchSource>("file");
  const [manualRows, setManualRows] = useState<Record<string, string>[]>([]);
  const [runningWorkflowId, setRunningWorkflowId] = useState<string | null>(null);
  const [batchRunProgress, setBatchRunProgress] = useState<BatchRunProgress | null>(null);
  const [runResult, setRunResult] = useState<WorkflowRunResult | null>(null);
  const [batchResult, setBatchResult] = useState<WorkflowBatchRunResult | null>(null);
  const [expandedBatchRows, setExpandedBatchRows] = useState<Set<number>>(new Set());
  const [runningOverlay, setRunningOverlay] = useState<{ workflowName: string } | null>(null);
  const [adoptingWorkflowId, setAdoptingWorkflowId] = useState<string | null>(null);

  const fetchWorkflows = useCallback(async () => {
    if (authLoading) return;
    if (!user) {
      setWorkflows([]);
      setLoading(false);
      return;
    }
    if (!instanceLoading && !instanceConnected) {
      setWorkflows([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const token = await user.getIdToken(true);
      const response = await fetch("/api/workflows", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Failed to fetch workflows."));
      }
      const data = (await response.json()) as { workflows?: unknown[] };
      setWorkflows((data.workflows ?? []).map(normalizeWorkflow));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Workflows could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [authLoading, instanceConnected, instanceLoading, user]);

  useEffect(() => {
    void fetchWorkflows();
  }, [fetchWorkflows]);

  const currentRows = useMemo(
    () => (parsedWorkbook && selectedSheet ? parsedWorkbook.sheets[selectedSheet] ?? [] : []),
    [parsedWorkbook, selectedSheet]
  );
  const headers = useMemo(
    () => (currentRows[headerRow - 1] ?? []).map((value) => cellText(value)),
    [currentRows, headerRow]
  );
  const selectedRows = useMemo(() => {
    if (!currentRows.length || dataEndRow < dataStartRow) return [];
    return currentRows
      .slice(dataStartRow - 1, dataEndRow)
      .map((row, index) => ({ rowNumber: dataStartRow + index, row }))
      .filter(({ row }) => !isEmptyRow(row));
  }, [currentRows, dataEndRow, dataStartRow]);
  const previewRows = selectedRows.slice(0, 5);

  const resetBatchState = () => {
    setRunMode("single");
    setParsedWorkbook(null);
    setSelectedSheet("");
    setHeaderRow(1);
    setDataStartRow(2);
    setDataEndRow(2);
    setBatchMappings({});
    setBatchSource("file");
    setManualRows([]);
  };

  const inferBatchMappings = (schema: WorkflowInputField[], nextHeaders: string[]) => {
    const normalizedHeaders = nextHeaders.map((header) => normalizedLabel(header));
    return Object.fromEntries(
      schema.map((field) => {
        const candidates = [field.name, field.label].map(normalizedLabel);
        const matchIndex = normalizedHeaders.findIndex((header) => candidates.includes(header));
        return [
          field.name,
          matchIndex >= 0
            ? ({ source: "column", columnIndex: matchIndex } satisfies BatchMapping)
            : ({ source: field.required ? "column" : "none" } satisfies BatchMapping),
        ];
      })
    );
  };

  const handleBatchFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !runWorkflow) return;
    try {
      // Lazy-load: xlsx büyük bir CJS kütüphanesi; sadece kullanıcı dosya
      // yüklediğinde indir, route'un ilk bundle/derlemesini şişirmesin.
      const XLSX = await import("xlsx");
      const buffer = await file.arrayBuffer();
      const workbook = XLSX.read(buffer, { type: "array" });
      const sheetNames = workbook.SheetNames;
      if (!sheetNames.length) throw new Error("The file has no sheets.");
      const sheets = Object.fromEntries(
        sheetNames.map((name) => [
          name,
          XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[name], {
            header: 1,
            defval: "",
            blankrows: false,
          }),
        ])
      );
      const firstSheet = sheetNames[0];
      const firstRows = sheets[firstSheet] ?? [];
      const nextHeaderRow = 1;
      const nextDataStart = Math.min(2, Math.max(firstRows.length, 1));
      const nextDataEnd = Math.min(Math.max(firstRows.length, nextDataStart), nextDataStart + 49);
      const nextHeaders = (firstRows[nextHeaderRow - 1] ?? []).map((value) => cellText(value));

      setParsedWorkbook({ fileName: file.name, sheetNames, sheets });
      setSelectedSheet(firstSheet);
      setHeaderRow(nextHeaderRow);
      setDataStartRow(nextDataStart);
      setDataEndRow(nextDataEnd);
      setBatchMappings(inferBatchMappings(runWorkflow.inputSchema ?? [], nextHeaders));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not read file.");
    } finally {
      event.target.value = "";
    }
  };

  const handleSheetChange = (sheetName: string) => {
    if (!parsedWorkbook || !runWorkflow) return;
    const rows = parsedWorkbook.sheets[sheetName] ?? [];
    const nextDataStart = Math.min(2, Math.max(rows.length, 1));
    const nextDataEnd = Math.min(Math.max(rows.length, nextDataStart), nextDataStart + 49);
    const nextHeaders = (rows[0] ?? []).map((value) => cellText(value));
    setSelectedSheet(sheetName);
    setHeaderRow(1);
    setDataStartRow(nextDataStart);
    setDataEndRow(nextDataEnd);
    setBatchMappings(inferBatchMappings(runWorkflow.inputSchema ?? [], nextHeaders));
  };

  const handleHeaderRowChange = (value: number) => {
    if (!runWorkflow) return;
    const nextHeaderRow = Math.max(1, Math.min(value, Math.max(currentRows.length, 1)));
    const nextDataStart = Math.max(nextHeaderRow + 1, dataStartRow);
    const nextDataEnd = Math.max(nextDataStart, dataEndRow);
    const nextHeaders = (currentRows[nextHeaderRow - 1] ?? []).map((cell) => cellText(cell));
    setHeaderRow(nextHeaderRow);
    setDataStartRow(nextDataStart);
    setDataEndRow(Math.min(nextDataEnd, currentRows.length || nextDataEnd));
    setBatchMappings(inferBatchMappings(runWorkflow.inputSchema ?? [], nextHeaders));
  };

  const updateBatchMapping = (fieldName: string, mapping: BatchMapping) => {
    setBatchMappings((prev) => ({ ...prev, [fieldName]: mapping }));
  };

  const batchMappingError = (workflow: Workflow): string | null => {
    if (!parsedWorkbook) return "Choose an XLSX or CSV file.";
    if (!selectedRows.length) return "No data rows selected.";
    if (selectedRows.length > MAX_BATCH_ROWS) return `Select ${MAX_BATCH_ROWS} rows or fewer.`;
    for (const field of workflow.inputSchema ?? []) {
      const mapping = batchMappings[field.name];
      if (!field.required) continue;
      if (!mapping || mapping.source === "none") return `${field.label} is required.`;
      if (mapping.source === "column" && mapping.columnIndex == null) {
        return `${field.label} needs a column.`;
      }
      if (mapping.source === "fixed" && !mapping.fixedValue?.trim()) {
        return `${field.label} needs a fixed value.`;
      }
    }
    return null;
  };

  const buildBatchRows = (workflow: Workflow): BatchRunRowPayload[] =>
    selectedRows.map(({ rowNumber, row }) => ({
      rowNumber,
      input: Object.fromEntries(
        (workflow.inputSchema ?? [])
          .map((field) => {
            const mapping = batchMappings[field.name];
            if (!mapping || mapping.source === "none") return null;
            if (mapping.source === "fixed") return [field.name, mapping.fixedValue?.trim() ?? ""];
            if (mapping.columnIndex == null) return [field.name, ""];
            return [field.name, cellText(row[mapping.columnIndex])];
          })
          .filter((entry): entry is [string, string] => entry !== null)
      ),
    }));

  const buildBatchRowPreviews = (
    workflow: Workflow,
    rows: BatchRunRowPayload[]
  ): Map<number, BatchRowPreview> => {
    const labelsByName = Object.fromEntries(
      (workflow.inputSchema ?? []).map((field) => [field.name, field.label])
    );
    return new Map(
      rows.map((row) => [
        row.rowNumber,
        {
          rowNumber: row.rowNumber,
          fields: Object.entries(row.input)
            .slice(0, 2)
            .map(([name, value]) => ({
              label: labelsByName[name] ?? name,
              value,
            })),
        },
      ])
    );
  };

  const makeEmptyManualRow = (workflow: Workflow): Record<string, string> =>
    Object.fromEntries((workflow.inputSchema ?? []).map((field) => [field.name, ""]));

  const isManualRowEmpty = (workflow: Workflow, row: Record<string, string>): boolean =>
    (workflow.inputSchema ?? []).every((field) => !(row[field.name] ?? "").trim());

  const selectBatchSource = (source: BatchSource) => {
    setBatchSource(source);
    if (source === "manual" && runWorkflow) {
      setManualRows((prev) => (prev.length ? prev : [makeEmptyManualRow(runWorkflow)]));
    }
  };

  const addManualRow = () => {
    if (!runWorkflow) return;
    setManualRows((prev) =>
      prev.length >= MAX_BATCH_ROWS ? prev : [...prev, makeEmptyManualRow(runWorkflow)]
    );
  };

  const removeManualRow = (index: number) => {
    setManualRows((prev) => prev.filter((_, i) => i !== index));
  };

  const updateManualCell = (index: number, name: string, value: string) => {
    setManualRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [name]: value } : row))
    );
  };

  // Boş satırları (tüm alanları boş) elemekle birlikte tablo sırasını koru: her
  // çalıştırmanın rowNumber'ı tablodaki 1-tabanlı satır konumudur, böylece
  // ilerleme/sonuç ve doğrulama uyarıları kullanıcının gördüğü satırla eşleşir.
  const buildManualRows = (workflow: Workflow): BatchRunRowPayload[] =>
    manualRows
      .map((row, index) => ({ index, row }))
      .filter(({ row }) => !isManualRowEmpty(workflow, row))
      .map(({ index, row }) => ({
        rowNumber: index + 1,
        input: Object.fromEntries(
          (workflow.inputSchema ?? []).map((field) => [field.name, (row[field.name] ?? "").trim()])
        ),
      }));

  const manualBatchError = (workflow: Workflow): string | null => {
    const rows = manualRows
      .map((row, index) => ({ index, row }))
      .filter(({ row }) => !isManualRowEmpty(workflow, row));
    if (!rows.length) return "Add at least one value to run.";
    if (rows.length > MAX_BATCH_ROWS) return `Add ${MAX_BATCH_ROWS} values or fewer.`;
    for (const { index, row } of rows) {
      for (const field of workflow.inputSchema ?? []) {
        if (field.required && !(row[field.name] ?? "").trim()) {
          return `${field.label} is required (row ${index + 1}).`;
        }
      }
    }
    return null;
  };

  const submitWorkflowBatchRun = async (workflow: Workflow) => {
    if (!user) return;
    const error =
      batchSource === "manual" ? manualBatchError(workflow) : batchMappingError(workflow);
    if (error) {
      toast.error(error);
      return;
    }
    setRunningWorkflowId(workflow.id);
    const rows = batchSource === "manual" ? buildManualRows(workflow) : buildBatchRows(workflow);
    const rowPreviews = buildBatchRowPreviews(workflow, rows);
    setBatchRunProgress({
      workflowId: workflow.id,
      workflowName: workflow.name,
      totalRows: rows.length,
      completedRows: 0,
      currentIndex: 0,
      succeeded: 0,
      failed: 0,
      skipped: 0,
    });
    try {
      const token = await user.getIdToken();
      const previewResponse = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}?action=batch-preview`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            source: "dashboard",
            rows,
            options: { continueOnError: true },
          }),
        }
      );
      if (!previewResponse.ok) {
        throw new Error(
          await getErrorMessage(previewResponse, "Could not prepare a safe batch preview.")
        );
      }
      const preview = (await previewResponse.json().catch(() => null)) as {
        status?: string;
        preview_token?: string;
        eligible_count?: number | null;
        action_count?: number | null;
        writeback_count?: number | null;
        actions?: Array<{ target?: string }>;
        findings?: string[];
      } | null;
      let previewToken: string | undefined;
      if (preview?.status !== "not_required") {
        setBatchRunProgress(null);
        const sampleTargets = (preview?.actions ?? [])
          .map((action) => action.target)
          .filter((target): target is string => Boolean(target))
          .slice(0, 3)
          .join(", ");
        const confirmed = await confirm({
          title: "Run this batch?",
          description: [
            `${preview?.eligible_count ?? 0} eligible item(s), ` +
              `${preview?.action_count ?? 0} action(s), ` +
              `${preview?.writeback_count ?? 0} write-back(s).`,
            sampleTargets ? `Sample targets: ${sampleTargets}.` : "",
            preview?.findings?.length ? preview.findings.join(" ") : "",
          ]
            .filter(Boolean)
            .join(" "),
          confirmLabel: "Run batch",
          cancelLabel: "Cancel",
        });
        if (!confirmed) return;
        previewToken = preview?.preview_token;
        setBatchRunProgress({
          workflowId: workflow.id,
          workflowName: workflow.name,
          totalRows: rows.length,
          completedRows: 0,
          currentIndex: 0,
          succeeded: 0,
          failed: 0,
          skipped: 0,
        });
      }
      await streamWorkflowBatchRun({
        token,
        workflowId: workflow.id,
        rows,
        previewToken,
        onEvent: (event) => {
          if (event.event === "started") {
            const totalRows = optionalNumber(event.data.totalRows) ?? rows.length;
            setBatchRunProgress((prev) =>
              prev
                ? {
                    ...prev,
                    totalRows,
                  }
                : prev
            );
            return;
          }

          if (event.event === "row_started") {
            const rowNumber = optionalNumber(event.data.rowNumber);
            const index = optionalNumber(event.data.index) ?? 0;
            setBatchRunProgress((prev) =>
              prev
                ? {
                    ...prev,
                    currentIndex: index,
                    currentRowNumber: rowNumber,
                    currentPreview: rowNumber ? rowPreviews.get(rowNumber) : undefined,
                  }
                : prev
            );
            return;
          }

          if (event.event === "row_finished") {
            const status = typeof event.data.status === "string" ? event.data.status : "";
            setBatchRunProgress((prev) =>
              prev
                ? {
                    ...prev,
                    completedRows: prev.completedRows + 1,
                    succeeded: prev.succeeded + (status === "success" ? 1 : 0),
                    failed: prev.failed + (status === "failed" ? 1 : 0),
                    skipped: prev.skipped + (status === "skipped" ? 1 : 0),
                  }
                : prev
            );
            return;
          }

          if (event.event === "completed") {
            const result = event.data as unknown as Omit<WorkflowBatchRunResult, "workflowName">;
            const functionalStatus = aggregateFunctionalStatus(result);
            setBatchRunProgress(null);
            setExpandedBatchRows(new Set());
            setBatchResult({ ...result, workflowName: workflow.name });
            notifyFunctionalResult(
              functionalStatus,
              `Batch completed: ${result.succeeded} executed, ${result.failed + result.skipped} need attention.`,
              result.status === "failed"
            );
            setRunWorkflow(null);
            resetBatchState();
            void fetchWorkflows();
            return;
          }

          if (event.event === "error") {
            const message =
              typeof event.data.message === "string"
                ? event.data.message
                : "Could not run workflow batch.";
            setBatchRunProgress((prev) => (prev ? { ...prev, error: message } : prev));
            throw new Error(message);
          }
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not run workflow batch.";
      setBatchRunProgress((prev) => (prev ? { ...prev, error: message } : prev));
      toast.error(message);
    } finally {
      setRunningWorkflowId(null);
    }
  };

  const handleToggle = async (workflow: Workflow) => {
    if (!user) return;
    if (isReadOnlyWorkflow(workflow)) return;
    const action = workflow.status === "active" ? "deactivate" : "activate";
    // Optimistic update
    setWorkflows((prev) =>
      prev.map((wf) =>
        wf.id === workflow.id
          ? { ...wf, status: action === "activate" ? "active" : "inactive" }
          : wf
      )
    );
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}?action=${action}`,
        {
          method: "PATCH",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Could not update workflow status."));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update workflow status.");
      void fetchWorkflows(); // revert by re-fetching
    }
  };

  const handleBulkDelete = async (targets: Workflow[]) => {
    if (!user || targets.length === 0) return;
    const single = targets.length === 1;
    const confirmed = await confirm({
      title: single ? "Delete workflow?" : "Delete workflows?",
      description: single
        ? `"${targets[0].name}" will be permanently removed.`
        : `${targets.length} workflows will be permanently removed.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      tone: "danger",
    });
    if (!confirmed) return;

    const ids = new Set(targets.map((wf) => wf.id));
    // Optimistic update
    setWorkflows((prev) => prev.filter((wf) => !ids.has(wf.id)));
    setBulkDeleting(true);
    try {
      const token = await user.getIdToken();
      const results = await Promise.allSettled(
        targets.map((wf) =>
          fetch(`/api/workflows/${encodeURIComponent(wf.id)}`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${token}` },
          }).then((response) => {
            if (!response.ok) throw new Error("Delete failed");
          })
        )
      );
      const failures = results.filter((result) => result.status === "rejected").length;
      if (failures > 0) {
        toast.error(`${targets.length - failures} deleted, ${failures} failed.`);
        void fetchWorkflows(); // resync truth from server
      } else {
        toast.success(
          single ? `"${targets[0].name}" deleted.` : `${targets.length} workflows deleted.`
        );
      }
    } catch {
      toast.error("Could not delete workflows.");
      void fetchWorkflows(); // revert
    } finally {
      setBulkDeleting(false);
      selection.exit();
    }
  };

  const handleDelete = (workflow: Workflow) => handleBulkDelete([workflow]);

  const handleAdopt = async (workflow: Workflow) => {
    if (!user) return;
    setAdoptingWorkflowId(workflow.id);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/workflows/${encodeURIComponent(workflow.id)}?action=adopt`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ source: "dashboard" }),
      });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Workflow could not be adopted."));
      }
      toast.success(`"${workflow.name}" adopted.`);
      await refreshInstance();
      void fetchWorkflows();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Workflow could not be adopted.");
    } finally {
      setAdoptingWorkflowId(null);
    }
  };

  const submitWorkflowRun = async (workflow: Workflow, input: Record<string, string>) => {
    if (!user) return;
    setRunningWorkflowId(workflow.id);
    setRunningOverlay({ workflowName: workflow.name });
    const startedAt = performance.now();
    try {
      const token = await user.getIdToken();
      const previewResponse = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}?action=preview-run`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ input, source: "dashboard" }),
        }
      );
      if (!previewResponse.ok) {
        throw new Error(
          await getErrorMessage(previewResponse, "Could not prepare a safe workflow preview.")
        );
      }
      const preview = (await previewResponse.json().catch(() => null)) as {
        status?: string;
        preview_token?: string;
        eligible_count?: number | null;
        action_count?: number | null;
        writeback_count?: number | null;
        actions?: Array<{ target?: string; subject?: string; kind?: string }>;
        findings?: string[];
      } | null;
      let previewToken: string | undefined;
      if (preview?.status !== "not_required") {
        setRunningOverlay(null);
        const sampleTargets = (preview?.actions ?? [])
          .map((action) => action.target)
          .filter((target): target is string => Boolean(target))
          .slice(0, 3)
          .join(", ");
        const description = [
          `${preview?.eligible_count ?? 0} eligible item(s), ` +
            `${preview?.action_count ?? 0} action(s), ` +
            `${preview?.writeback_count ?? 0} write-back(s).`,
          sampleTargets ? `Targets: ${sampleTargets}.` : "",
          preview?.findings?.length ? preview.findings.join(" ") : "",
        ]
          .filter(Boolean)
          .join(" ");
        const confirmed = await confirm({
          title: "Run this workflow?",
          description,
          confirmLabel: "Run",
          cancelLabel: "Cancel",
        });
        if (!confirmed) return;
        previewToken = preview?.preview_token;
        setRunningOverlay({ workflowName: workflow.name });
      }
      const response = await fetch(
        `/api/workflows/${encodeURIComponent(workflow.id)}?action=run`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ input, source: "dashboard", previewToken }),
        }
      );
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Could not run workflow."));
      }
      const result = (await response.json().catch(() => null)) as {
        success?: boolean;
        execution_id?: string;
        status?: string;
        functional_status?: WorkflowFunctionalStatus;
        functionalStatus?: WorkflowFunctionalStatus;
        assessment?: WorkflowRunAssessment;
        claimable_outcome?: unknown;
        claimableOutcome?: unknown;
        summary?: string;
        failed_node?: string;
        error?: string;
        outputs?: WorkflowRunOutput[];
        artifacts?: ArtifactPreviewData[];
        presentation?: WorkflowResultPresentation | null;
      } | null;
      await ensureMinOverlay(startedAt);
      setRunningOverlay(null);
      const executionFailed =
        result?.success === false || ["error", "failed", "crashed"].includes(result?.status ?? "");
      const functionalStatus = result?.functional_status ?? result?.functionalStatus;
      notifyFunctionalResult(
        functionalStatus,
        result?.error || result?.summary || `Workflow ${result?.status || "triggered"}.`,
        executionFailed
      );
      setRunResult({
        workflowName: workflow.name,
        executionId: result?.execution_id,
        status: result?.status,
        functionalStatus,
        assessment: result?.assessment,
        claimableOutcome: result?.claimable_outcome ?? result?.claimableOutcome,
        summary: result?.summary,
        failedNode: result?.failed_node,
        error: result?.error,
        outputs: result?.outputs,
        artifacts: result?.artifacts,
        presentation: result?.presentation,
      });
      setRunWorkflow(null);
      setRunValues({});
      void fetchWorkflows();
    } catch (error) {
      await ensureMinOverlay(startedAt);
      setRunningOverlay(null);
      toast.error(error instanceof Error ? error.message : "Could not run workflow.");
    } finally {
      setRunningWorkflowId(null);
    }
  };

  const handleRun = (workflow: Workflow) => {
    const schema = workflow.inputSchema ?? [];
    if (schema.length === 0) {
      void submitWorkflowRun(workflow, {});
      return;
    }
    resetBatchState();
    setRunWorkflow(workflow);
    setRunValues(
      Object.fromEntries(schema.map((field) => [field.name, runValues[field.name] ?? ""]))
    );
  };

  const handleRunSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!runWorkflow) return;
    const missing = (runWorkflow.inputSchema ?? []).find(
      (field) => field.required && !runValues[field.name]?.trim()
    );
    if (missing) {
      toast.error(`${missing.label} is required.`);
      return;
    }
    void submitWorkflowRun(runWorkflow, runValues);
  };

  const handleBatchRunSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!runWorkflow) return;
    void submitWorkflowBatchRun(runWorkflow);
  };

  const renderRunField = (field: WorkflowInputField) => {
    const value = runValues[field.name] ?? "";
    const commonProps = {
      id: `run-${field.name}`,
      name: field.name,
      value,
      placeholder: field.placeholder,
      required: field.required,
      onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setRunValues((prev) => ({ ...prev, [field.name]: event.target.value })),
    };
    if (field.type === "textarea") {
      return <Textarea {...commonProps} rows={5} className="text-[14px]" />;
    }
    return (
      <Input
        {...commonProps}
        type={field.type === "email" ? "email" : "text"}
        className="h-9 text-[14px]"
      />
    );
  };

  const renderManualCell = (field: WorkflowInputField, index: number) => {
    const value = manualRows[index]?.[field.name] ?? "";
    const commonProps = {
      value,
      placeholder: field.placeholder,
      onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        updateManualCell(index, field.name, event.target.value),
    };
    if (field.type === "textarea") {
      return <Textarea {...commonProps} rows={1} className="min-h-9 text-[14px]" />;
    }
    return (
      <Input
        {...commonProps}
        type={field.type === "email" ? "email" : "text"}
        className="h-9 text-[14px]"
      />
    );
  };

  const renderBatchMappingField = (field: WorkflowInputField) => {
    const mapping = batchMappings[field.name] ?? { source: field.required ? "column" : "none" };
    const selectValue =
      mapping.source === "fixed"
        ? "__fixed"
        : mapping.source === "none"
          ? "__none"
          : String(mapping.columnIndex ?? "");

    return (
      <div key={field.name} className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-[140px_1fr]">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-foreground">{field.label}</p>
          <p className="text-[12px] text-muted-foreground">{field.required ? "Required" : "Optional"}</p>
        </div>
        <div className="flex flex-col gap-2">
          <select
            value={selectValue}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "__fixed") {
                updateBatchMapping(field.name, {
                  source: "fixed",
                  fixedValue: mapping.fixedValue ?? "",
                });
                return;
              }
              if (value === "__none") {
                updateBatchMapping(field.name, { source: "none" });
                return;
              }
              updateBatchMapping(field.name, {
                source: "column",
                columnIndex: Number(value),
              });
            }}
            className="h-9 rounded-md border border-input bg-background px-3 text-[14px] outline-none transition-colors hover:border-gray-400 focus:border-conduut-500 focus:ring-2 focus:ring-conduut-500/20"
          >
            {!field.required && <option value="__none">Do not send</option>}
            <option value="">Select column</option>
            {headers.map((header, index) => (
              <option key={`${header}-${index}`} value={index}>
                {columnLabel(headers, index)}
              </option>
            ))}
            <option value="__fixed">Fixed value</option>
          </select>
          {mapping.source === "fixed" && (
            <Input
              value={mapping.fixedValue ?? ""}
              placeholder={field.placeholder}
              onChange={(event) =>
                updateBatchMapping(field.name, {
                  source: "fixed",
                  fixedValue: event.target.value,
                })
              }
              className="h-9 text-[14px]"
            />
          )}
        </div>
      </div>
    );
  };

  const toggleBatchRow = (rowNumber: number) => {
    setExpandedBatchRows((prev) => {
      const next = new Set(prev);
      if (next.has(rowNumber)) next.delete(rowNumber);
      else next.add(rowNumber);
      return next;
    });
  };

  const batchRowHasDetail = (row: BatchRunRowResult): boolean =>
    Boolean(
      row.presentation?.fields?.length ||
        row.outputs?.length ||
        row.assessment ||
        claimableOutcomeText(row.claimable_outcome ?? row.claimableOutcome) ||
        row.execution_id
    );

  const batchRowSummary = (row: BatchRunRowResult): string => {
    if (row.error) return row.error;
    const field = row.presentation?.fields?.[0];
    if (field) {
      const value =
        field.value == null
          ? ""
          : typeof field.value === "object"
            ? JSON.stringify(field.value)
            : String(field.value);
      return `${field.label}: ${value}`;
    }
    if (row.summary) return row.summary;
    const assessmentWarning = row.assessment?.warnings
      ?.map((warning) => (typeof warning === "string" ? warning : warning.message))
      .find(Boolean);
    if (assessmentWarning) return assessmentWarning;
    return row.execution_id || "-";
  };

  const filtered = workflows.filter((wf) => {
    const matchesSearch =
      wf.name.toLowerCase().includes(search.toLowerCase()) ||
      (wf.description?.toLowerCase().includes(search.toLowerCase()) ?? false);
    const matchesStatus = statusFilter === "all" || wf.status === statusFilter;
    return matchesSearch && matchesStatus;
  });
  const bulkSelectable = filtered.filter((workflow) => !isReadOnlyWorkflow(workflow));

  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-medium text-foreground">Workflows</h1>
        <Link href="/chat">
          <Button size="sm" className="gap-1.5">
            <Plus className="h-4 w-4" />
            New Workflow
          </Button>
        </Link>
      </div>

      {connectionRequired ? (
        <div className="mb-5">
          <ConnectionCallout
            compact
            statusLabel={instance?.connectionStatus ? instance.connectionStatus.replaceAll("_", " ") : undefined}
            description={
              instanceError ??
              "Connect your own n8n server before Conduut can list workflows or adopt automations that already live there."
            }
          />
        </div>
      ) : null}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search workflows..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-[14px]"
          />
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-card">
          {(["all", "active", "inactive"] as const).map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1 rounded-md text-[13px] font-medium transition-colors capitalize ${
                statusFilter === status
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {status === "all" ? "All" : status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>
        <div className="ml-auto">
          <Button
            type="button"
            variant={selection.selecting ? "default" : "outline"}
            size="sm"
            onClick={() => (selection.selecting ? selection.exit() : selection.enter())}
            disabled={bulkSelectable.length === 0}
            className="gap-1.5"
          >
            <CheckSquare className="h-4 w-4" />
            {selection.selecting ? "Done" : "Select"}
          </Button>
        </div>
      </div>

      {selection.selecting && (
        <BulkActionBar
          count={selection.selectedCount}
          total={bulkSelectable.length}
          allSelected={bulkSelectable.length > 0 && selection.selectedCount === bulkSelectable.length}
          busy={bulkDeleting}
          onSelectAll={() => selection.selectAll(bulkSelectable.map((wf) => wf.id))}
          onClear={selection.clear}
          onCancel={selection.exit}
          onDelete={() =>
            void handleBulkDelete(bulkSelectable.filter((wf) => selection.isSelected(wf.id)))
          }
        />
      )}

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      ) : filtered.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((wf) => (
            <WorkflowCard
              key={wf.id}
              workflow={wf}
              isRunning={runningWorkflowId === wf.id}
              isAdopting={adoptingWorkflowId === wf.id}
              selectable={selection.selecting}
              selected={selection.isSelected(wf.id)}
              onToggleSelect={(w) => selection.toggle(w.id)}
              onRun={(w) => handleRun(w)}
              onToggle={(w) => void handleToggle(w)}
              onDelete={(w) => void handleDelete(w)}
              onAdopt={(w) => void handleAdopt(w)}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted mb-4">
            <WorkflowIcon className="h-8 w-8 text-muted-foreground" />
          </div>
          <h2 className="text-[16px] font-medium text-foreground mb-1">
            {search || statusFilter !== "all"
              ? "No matching workflows"
              : "No workflows yet"}
          </h2>
          <p className="text-[14px] text-muted-foreground mb-6 max-w-xs">
            {search || statusFilter !== "all"
              ? "Try adjusting your search or filter."
              : connectionRequired
                ? "Connect your automation server first, then adopt or create workflows."
                : "Start a conversation with the AI agent to create your first workflow."}
          </p>
          {!search && statusFilter === "all" && !connectionRequired && (
            <Link href="/chat">
              <Button size="sm">
                <Plus className="h-4 w-4" />
                Create your first workflow
              </Button>
            </Link>
          )}
          {!search && statusFilter === "all" && connectionRequired ? (
            <Link href="/dashboard/settings?tab=automation-server">
              <Button size="sm">Connect automation server</Button>
            </Link>
          ) : null}
        </div>
      )}

      {runWorkflow && !batchRunProgress && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workflow-run-title"
          onClick={() => {
            if (!runningWorkflowId) {
              setRunWorkflow(null);
              resetBatchState();
            }
          }}
        >
          <form
            className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-xl"
            onClick={(event) => event.stopPropagation()}
            onSubmit={runMode === "single" ? handleRunSubmit : handleBatchRunSubmit}
          >
            <div className="mb-4">
              <h2 id="workflow-run-title" className="text-[16px] font-medium text-foreground">
                Run {runWorkflow.name}
              </h2>
            </div>

            <div className="mb-4 inline-flex rounded-lg border border-border bg-muted/40 p-1">
              {(["single", "batch"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setRunMode(mode)}
                  className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    runMode === mode
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {mode === "single" ? "Run once" : "Run batch"}
                </button>
              ))}
            </div>

            {runMode === "single" ? (
              <div className="flex flex-col gap-3">
                {(runWorkflow.inputSchema ?? []).map((field) => (
                  <label key={field.name} className="flex flex-col gap-1.5">
                    <span className="text-[13px] font-medium text-foreground">
                      {field.label}
                    </span>
                    {renderRunField(field)}
                  </label>
                ))}
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                <div className="inline-flex self-start rounded-lg border border-border bg-muted/40 p-1">
                  {(["file", "manual"] as const).map((source) => (
                    <button
                      key={source}
                      type="button"
                      onClick={() => selectBatchSource(source)}
                      className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                        batchSource === source
                          ? "bg-card text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {source === "file" ? "File" : "Manual entry"}
                    </button>
                  ))}
                </div>

                {batchSource === "file" ? (
                <>
                <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
                  <label className="flex flex-col gap-1.5">
                    <span className="text-[13px] font-medium text-foreground">File</span>
                    <input
                      type="file"
                      accept=".xlsx,.xls,.csv"
                      onChange={handleBatchFileChange}
                      className="h-9 rounded-md border border-input bg-background px-3 py-1.5 text-[13px] file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-2 file:py-1 file:text-[12px] file:font-medium"
                    />
                  </label>
                  {parsedWorkbook && (
                    <div className="flex h-9 items-center gap-2 rounded-md border border-border px-3 text-[13px] text-muted-foreground">
                      <Upload className="h-4 w-4" />
                      <span className="max-w-[220px] truncate">{parsedWorkbook.fileName}</span>
                    </div>
                  )}
                </div>

                {parsedWorkbook && (
                  <>
                    <div className="grid gap-3 md:grid-cols-4">
                      <label className="flex flex-col gap-1.5 md:col-span-1">
                        <span className="text-[13px] font-medium text-foreground">Sheet</span>
                        <select
                          value={selectedSheet}
                          onChange={(event) => handleSheetChange(event.target.value)}
                          className="h-9 rounded-md border border-input bg-background px-3 text-[14px] outline-none transition-colors hover:border-gray-400 focus:border-conduut-500 focus:ring-2 focus:ring-conduut-500/20"
                        >
                          {parsedWorkbook.sheetNames.map((name) => (
                            <option key={name} value={name}>
                              {name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="flex flex-col gap-1.5">
                        <span className="text-[13px] font-medium text-foreground">Header row</span>
                        <Input
                          type="number"
                          min={1}
                          max={Math.max(currentRows.length, 1)}
                          value={headerRow}
                          onChange={(event) => handleHeaderRowChange(Number(event.target.value))}
                          className="h-9 text-[14px]"
                        />
                      </label>
                      <label className="flex flex-col gap-1.5">
                        <span className="text-[13px] font-medium text-foreground">Start row</span>
                        <Input
                          type="number"
                          min={headerRow + 1}
                          max={Math.max(currentRows.length, headerRow + 1)}
                          value={dataStartRow}
                          onChange={(event) =>
                            setDataStartRow(
                              Math.max(headerRow + 1, Number(event.target.value) || headerRow + 1)
                            )
                          }
                          className="h-9 text-[14px]"
                        />
                      </label>
                      <label className="flex flex-col gap-1.5">
                        <span className="text-[13px] font-medium text-foreground">End row</span>
                        <Input
                          type="number"
                          min={dataStartRow}
                          max={Math.max(currentRows.length, dataStartRow)}
                          value={dataEndRow}
                          onChange={(event) =>
                            setDataEndRow(Math.max(dataStartRow, Number(event.target.value) || dataStartRow))
                          }
                          className="h-9 text-[14px]"
                        />
                      </label>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                      {(runWorkflow.inputSchema ?? []).map((field) => renderBatchMappingField(field))}
                    </div>

                    <div className="rounded-md border border-border">
                      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
                        <div className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-foreground">
                          <Table2 className="h-4 w-4 text-muted-foreground" />
                          <span className="truncate">Preview</span>
                        </div>
                        <span className="text-[12px] text-muted-foreground">
                          {selectedRows.length} rows
                        </span>
                      </div>
                      <div className="max-h-56 overflow-auto">
                        <table className="w-full min-w-[520px] text-left text-[12px]">
                          <thead className="bg-muted/60 text-muted-foreground">
                            <tr>
                              <th className="w-20 px-3 py-2 font-medium">Row</th>
                              {headers.slice(0, 6).map((header, index) => (
                                <th key={`${header}-${index}`} className="px-3 py-2 font-medium">
                                  {columnLabel(headers, index)}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {previewRows.map(({ rowNumber, row }) => (
                              <tr key={rowNumber} className="border-t border-border">
                                <td className="px-3 py-2 text-muted-foreground">{rowNumber}</td>
                                {headers.slice(0, 6).map((_header, index) => (
                                  <td key={index} className="max-w-[180px] truncate px-3 py-2">
                                    {cellText(row[index])}
                                  </td>
                                ))}
                              </tr>
                            ))}
                            {!previewRows.length && (
                              <tr>
                                <td className="px-3 py-4 text-muted-foreground" colSpan={7}>
                                  No rows selected.
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </>
                )}
                </>
                ) : (
                  <div className="flex flex-col gap-3">
                    <div className="rounded-md border border-border">
                      <div className="max-h-80 overflow-auto">
                        <table className="w-full min-w-[520px] text-left text-[13px]">
                          <thead className="bg-muted/60 text-muted-foreground">
                            <tr>
                              <th className="w-12 px-3 py-2 font-medium">#</th>
                              {(runWorkflow.inputSchema ?? []).map((field) => (
                                <th key={field.name} className="px-3 py-2 font-medium">
                                  {field.label}
                                </th>
                              ))}
                              <th className="w-12 px-3 py-2" />
                            </tr>
                          </thead>
                          <tbody>
                            {manualRows.map((_row, index) => (
                              <tr key={index} className="border-t border-border align-top">
                                <td className="px-3 py-3 text-muted-foreground">{index + 1}</td>
                                {(runWorkflow.inputSchema ?? []).map((field) => (
                                  <td key={field.name} className="min-w-[160px] px-2 py-2">
                                    {renderManualCell(field, index)}
                                  </td>
                                ))}
                                <td className="px-2 py-2">
                                  <button
                                    type="button"
                                    onClick={() => removeManualRow(index)}
                                    disabled={manualRows.length <= 1}
                                    aria-label="Remove row"
                                    className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                                  >
                                    <X className="h-4 w-4" />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={addManualRow}
                        disabled={manualRows.length >= MAX_BATCH_ROWS}
                        className="gap-1.5"
                      >
                        <Plus className="h-4 w-4" />
                        Add row
                      </Button>
                      <span className="text-[12px] text-muted-foreground">
                        {manualRows.length}/{MAX_BATCH_ROWS}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={runningWorkflowId === runWorkflow.id}
                onClick={() => {
                  setRunWorkflow(null);
                  resetBatchState();
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={runningWorkflowId === runWorkflow.id}>
                {runningWorkflowId === runWorkflow.id
                  ? "Running..."
                  : runMode === "batch"
                    ? "Run batch"
                    : "Run"}
              </Button>
            </div>
          </form>
        </div>
      )}

      {batchRunProgress && (
        <BatchRunProgressDialog
          progress={batchRunProgress}
          onClose={() => {
            setBatchRunProgress(null);
            setRunWorkflow(null);
            resetBatchState();
          }}
        />
      )}

      {runResult && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workflow-run-result-title"
          onClick={() => setRunResult(null)}
        >
          <div
            className="w-full max-w-2xl rounded-lg border border-border bg-card p-5 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2
                  id="workflow-run-result-title"
                  className="truncate text-[16px] font-medium text-foreground"
                >
                  {runResult.workflowName}
                </h2>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  {runResult.summary || `Workflow ${runResult.status || "triggered"}.`}
                </p>
                {(runResult.functionalStatus || runResult.executionId) && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <FunctionalStatusBadge status={runResult.functionalStatus} />
                    {runResult.executionId && (
                      <Link
                        href="/dashboard/runs"
                        className="text-[12px] font-medium text-conduut-600 hover:underline"
                      >
                        View run details
                      </Link>
                    )}
                  </div>
                )}
              </div>
              <Button size="sm" variant="outline" onClick={() => setRunResult(null)}>
                Close
              </Button>
            </div>
            <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto pr-1">
              {runResult.error && (
                <div className="rounded-md border border-error/30 bg-error/5 p-3">
                  <p className="text-[13px] font-medium text-error">Workflow run failed</p>
                  {runResult.failedNode && (
                    <p className="mt-1 text-[12px] text-muted-foreground">
                      Failed step: {runResult.failedNode}
                    </p>
                  )}
                  <p className="mt-1 whitespace-pre-wrap break-words text-[13px] text-foreground">
                    {runResult.error}
                  </p>
                </div>
              )}
              <AssessmentDetails
                assessment={runResult.assessment}
                claimableOutcome={runResult.claimableOutcome}
              />
              {runResult.presentation && runResult.presentation.fields.length > 0 && (
                <WorkflowResultView presentation={runResult.presentation} />
              )}
              {(runResult.artifacts ?? []).map((artifact, index) => (
                <ArtifactPreview key={index} data={artifact} />
              ))}
              <RunOutputsDetails outputs={runResult.outputs ?? []} />
              {!runResult.presentation?.fields.length &&
                !(runResult.outputs ?? []).length &&
                !(runResult.artifacts ?? []).length && (
                  <p className="text-[13px] text-muted-foreground">
                    {runResult.error
                      ? "No output was produced before the failure."
                      : "Workflow çalıştı ama gösterilecek bir çıktı üretmedi."}
                  </p>
                )}
            </div>
          </div>
        </div>
      )}

      {batchResult && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workflow-batch-result-title"
          onClick={() => {
            setBatchResult(null);
            setExpandedBatchRows(new Set());
          }}
        >
          <div
            className="w-full max-w-4xl rounded-lg border border-border bg-card p-5 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2
                  id="workflow-batch-result-title"
                  className="truncate text-[16px] font-medium text-foreground"
                >
                  {batchResult.workflowName}
                </h2>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  {batchResult.succeeded} succeeded, {batchResult.failed} failed,{" "}
                  {batchResult.skipped} skipped
                </p>
                <div className="mt-2">
                  <FunctionalStatusBadge status={aggregateFunctionalStatus(batchResult)} />
                </div>
                <BatchFunctionalCounts result={batchResult} />
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setBatchResult(null);
                  setExpandedBatchRows(new Set());
                }}
              >
                Close
              </Button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto">
              <AssessmentDetails
                assessment={batchResult.assessment}
                claimableOutcome={batchResult.claimable_outcome ?? batchResult.claimableOutcome}
              />
              <table className="w-full min-w-[640px] text-left text-[13px]">
                <thead className="bg-muted/60 text-muted-foreground">
                  <tr>
                    <th className="w-10 px-3 py-2" />
                    <th className="w-20 px-3 py-2 font-medium">Row</th>
                    <th className="w-28 px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {batchResult.results.map((row) => {
                    const hasDetail = batchRowHasDetail(row);
                    const expanded = expandedBatchRows.has(row.rowNumber);
                    return (
                      <Fragment key={row.rowNumber}>
                        <tr
                          className={`border-t border-border ${
                            hasDetail ? "cursor-pointer hover:bg-muted/40" : ""
                          }`}
                          onClick={hasDetail ? () => toggleBatchRow(row.rowNumber) : undefined}
                        >
                          <td className="px-3 py-2 text-muted-foreground">
                            {hasDetail && (
                              <ChevronRight
                                className={`h-4 w-4 transition-transform ${
                                  expanded ? "rotate-90" : ""
                                }`}
                              />
                            )}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">{row.rowNumber}</td>
                          <td className="px-3 py-2">
                            {row.functional_status || row.functionalStatus ? (
                              <FunctionalStatusBadge
                                status={row.functional_status ?? row.functionalStatus}
                              />
                            ) : (
                              <span className="capitalize">{row.status}</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">
                            <span className="block max-w-[420px] truncate">
                              {batchRowSummary(row)}
                            </span>
                          </td>
                        </tr>
                        {hasDetail && expanded && (
                          <tr className="border-t border-border bg-muted/20">
                            <td />
                            <td colSpan={3} className="px-3 py-3">
                              <div className="flex flex-col gap-3">
                                <AssessmentDetails
                                  assessment={row.assessment}
                                  claimableOutcome={row.claimable_outcome ?? row.claimableOutcome}
                                />
                                {row.presentation && row.presentation.fields.length > 0 && (
                                  <WorkflowResultView presentation={row.presentation} />
                                )}
                                <RunOutputsDetails outputs={row.outputs ?? []} />
                                {row.execution_id && (
                                  <Link
                                    href="/dashboard/runs"
                                    className="text-[12px] font-medium text-conduut-600 hover:underline"
                                  >
                                    View run details
                                  </Link>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
              {batchResult.results.some((row) => row.artifacts?.length) && (
                <div className="mt-4 flex flex-col gap-3">
                  {batchResult.results.flatMap((row) =>
                    (row.artifacts ?? []).map((artifact, index) => (
                      <ArtifactPreview
                        key={`${row.rowNumber}-${index}`}
                        data={artifact}
                        metadata={
                          <span className="text-[12px] text-muted-foreground">
                            Row {row.rowNumber}
                          </span>
                        }
                      />
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {runningOverlay && (
        <WorkflowRunningOverlay workflowName={runningOverlay.workflowName} />
      )}
    </div>
  );
}
