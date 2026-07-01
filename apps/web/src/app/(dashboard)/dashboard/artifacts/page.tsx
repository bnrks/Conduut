"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CheckSquare, ExternalLink, FileSearch, Mail, MessageSquare, Table2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { ServiceLogo } from "@/components/dashboard/service-logo";
import { BulkActionBar } from "@/components/dashboard/bulk-action-bar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { useMultiSelect } from "@/hooks/use-multi-select";
import { cn } from "@/lib/utils";
import type {
  ArtifactPreviewRow,
  ArtifactPreviewTable,
  ArtifactPreviewMessage,
  ArtifactRecord,
  ArtifactService,
} from "@/types/artifact";

type ServiceFilter = "all" | ArtifactService;
type OriginKind = ArtifactRecord["origin"]["kind"];

const FILTERS: { label: string; value: ServiceFilter }[] = [
  { label: "All", value: "all" },
  { label: "Sheets", value: "google_sheets" },
  { label: "Gmail", value: "gmail" },
];

const SHEETS_METADATA_COLUMNS = new Set([
  "spreadsheet id",
  "spreadsheetid",
  "title",
  "sheet",
  "range",
  "updated range",
]);
const ACTION_TITLE_PATTERN =
  /^Google Sheets (spreadsheet created|range updated|tab created|range read|row added|rows captured|updated)$/i;

interface SheetArtifactItem {
  kind: "sheet";
  key: string;
  artifactIds: string[];
  artifactCount: number;
  title?: string;
  spreadsheetId?: string;
  sheetName?: string;
  range?: string;
  url?: string;
  latestAt: string;
  latestTime: number;
  originKinds: OriginKind[];
  previewTable?: ArtifactPreviewTable;
  previewTime: number;
}

interface GenericArtifactItem {
  kind: "generic";
  key: string;
  artifact: ArtifactRecord;
  latestAt: string;
  latestTime: number;
}

type DashboardArtifactItem = SheetArtifactItem | GenericArtifactItem;

async function getErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as {
    detail?: { message?: string } | string;
    message?: string;
  } | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  if (typeof payload?.message === "string") return payload.message;
  return fallback;
}

function serviceLabel(service: ArtifactService): string {
  if (service === "gmail") return "Gmail";
  return "Google Sheets";
}

function originLabel(origin: ArtifactRecord["origin"]): string {
  if (origin.kind === "workflow_run") return "Workflow run";
  return "Chat";
}

function originKindLabel(kind: OriginKind): string {
  if (kind === "workflow_run") return "Workflow run";
  return "Chat";
}

function originSummary(kinds: OriginKind[]): string {
  if (kinds.length === 0) return "Unknown source";
  return kinds.map(originKindLabel).join(" + ");
}

function formatDateTime(iso: string): string {
  if (!iso) return "Unknown time";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function dateValue(iso: string): number {
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? 0 : value;
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function rowCell(row: ArtifactPreviewRow, column: string, columnIndex: number): unknown {
  if (Array.isArray(row)) {
    return row[columnIndex];
  }
  return row[column];
}

function normalizedColumn(value: string): string {
  return value.trim().toLowerCase();
}

function asNonEmptyString(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    const text = String(value).trim();
    return text || undefined;
  }
  return undefined;
}

function sourceString(artifact: ArtifactRecord, key: string): string | undefined {
  return asNonEmptyString(artifact.source?.[key]);
}

function firstTableValue(
  table: ArtifactPreviewTable | undefined,
  candidateColumns: string[]
): string | undefined {
  const firstRow = table?.rows?.[0];
  if (!table || !firstRow) return undefined;
  const candidates = new Set(candidateColumns.map(normalizedColumn));
  for (const [index, column] of table.columns.entries()) {
    if (candidates.has(normalizedColumn(column))) {
      return asNonEmptyString(rowCell(firstRow, column, index));
    }
  }
  return undefined;
}

function isSheetsMetadataTable(table: ArtifactPreviewTable | undefined): boolean {
  if (!table || table.columns.length === 0) return false;
  const normalized = table.columns.map(normalizedColumn);
  const hasSpreadsheetIdentity = normalized.some((column) =>
    column === "spreadsheet id" || column === "spreadsheetid"
  );
  return hasSpreadsheetIdentity && normalized.every((column) => SHEETS_METADATA_COLUMNS.has(column));
}

function spreadsheetIdFromUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;
  const match = url.match(/\/spreadsheets\/d\/([^/?#]+)/);
  return match?.[1];
}

function sheetNameFromRange(range: string | undefined): string | undefined {
  if (!range) return undefined;
  const trimmed = range.trim();
  if (!trimmed) return undefined;
  const sheetPart = trimmed.includes("!") ? trimmed.split("!")[0] : trimmed;
  if (!sheetPart || /^[A-Z]+[0-9]*(:[A-Z]+[0-9]*)?$/i.test(sheetPart)) {
    return undefined;
  }
  return sheetPart.replace(/^'(.*)'$/, "$1").replace(/''/g, "'");
}

function displayTitleFromArtifact(artifact: ArtifactRecord): string | undefined {
  return (
    firstTableValue(artifact.table, ["Title", "Spreadsheet title", "Name"]) ??
    sourceString(artifact, "title") ??
    sourceString(artifact, "spreadsheetTitle") ??
    (ACTION_TITLE_PATTERN.test(artifact.title) ? undefined : artifact.title)
  );
}

function tableHasPreviewData(table: ArtifactPreviewTable | undefined): table is ArtifactPreviewTable {
  return Boolean(table && table.columns.length > 0 && table.rows.length > 0);
}

function buildSheetKey(artifact: ArtifactRecord): string {
  const spreadsheetId =
    sourceString(artifact, "spreadsheetId") ?? spreadsheetIdFromUrl(artifact.url);
  if (spreadsheetId) return `sheet:${spreadsheetId}`;
  if (artifact.url) return `sheet:url:${artifact.url}`;
  return `sheet:artifact:${artifact.id}`;
}

function buildDashboardItems(artifacts: ArtifactRecord[]): DashboardArtifactItem[] {
  const sheetItems = new Map<string, SheetArtifactItem>();
  const genericItems: DashboardArtifactItem[] = [];

  for (const artifact of artifacts) {
    const latestTime = dateValue(artifact.createdAt);
    if (artifact.service !== "google_sheets") {
      genericItems.push({
        kind: "generic",
        key: artifact.id,
        artifact,
        latestAt: artifact.createdAt,
        latestTime,
      });
      continue;
    }

    const key = buildSheetKey(artifact);
    const current =
      sheetItems.get(key) ??
      ({
        kind: "sheet",
        key,
        artifactIds: [],
        artifactCount: 0,
        latestAt: artifact.createdAt,
        latestTime,
        originKinds: [],
        previewTime: 0,
      } satisfies SheetArtifactItem);

    current.artifactCount += 1;
    if (!current.artifactIds.includes(artifact.id)) {
      current.artifactIds.push(artifact.id);
    }
    if (latestTime >= current.latestTime) {
      current.latestAt = artifact.createdAt;
      current.latestTime = latestTime;
    }
    if (!current.originKinds.includes(artifact.origin.kind)) {
      current.originKinds.push(artifact.origin.kind);
    }

    current.spreadsheetId =
      current.spreadsheetId ??
      sourceString(artifact, "spreadsheetId") ??
      spreadsheetIdFromUrl(artifact.url);
    current.url = current.url ?? artifact.url;
    current.title = current.title ?? displayTitleFromArtifact(artifact);

    const tableSheetName = firstTableValue(artifact.table, ["Sheet", "Sheet name", "Tab"]);
    const range = sourceString(artifact, "range");
    current.sheetName =
      current.sheetName ??
      tableSheetName ??
      sourceString(artifact, "sheetName") ??
      sourceString(artifact, "sheet") ??
      sheetNameFromRange(range);
    current.range = current.range ?? range;

    if (
      tableHasPreviewData(artifact.table) &&
      !isSheetsMetadataTable(artifact.table) &&
      latestTime >= current.previewTime
    ) {
      current.previewTable = artifact.table;
      current.previewTime = latestTime;
    }

    sheetItems.set(key, current);
  }

  return [...sheetItems.values(), ...genericItems].sort(
    (left, right) => right.latestTime - left.latestTime
  );
}

function itemArtifactIds(item: DashboardArtifactItem): string[] {
  return item.kind === "sheet" ? item.artifactIds : [item.artifact.id];
}

function PreviewTable({ table }: { table: ArtifactPreviewTable }) {
  const columns = table.columns.slice(0, 5);
  const rows = table.rows.slice(0, 4);

  return (
    <div className="max-w-full overflow-x-auto border-t border-border">
      <table className="min-w-full table-fixed border-collapse text-left text-[12px]">
        <thead className="bg-muted/60 text-muted-foreground">
          <tr>
            {columns.map((column, columnIndex) => (
              <th
                key={`${column}-${columnIndex}`}
                className="max-w-[160px] border-b border-border px-3 py-2 font-medium"
              >
                <span className="block truncate">{column}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-border/70 last:border-0">
              {columns.map((column, columnIndex) => (
                <td key={`${rowIndex}-${column}`} className="max-w-[160px] px-3 py-2">
                  <span className="block truncate" title={cellText(rowCell(row, column, columnIndex))}>
                    {cellText(rowCell(row, column, columnIndex))}
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function messageValueList(value: string[] | undefined): string | undefined {
  if (!Array.isArray(value) || value.length === 0) return undefined;
  return value.filter(Boolean).join(", ") || undefined;
}

function MessagePreview({ message }: { message: ArtifactPreviewMessage }) {
  const rows = [
    ["To", messageValueList(message.to)],
    ["From", message.fromEmail],
    ["Subject", message.subject],
    ["Message ID", message.messageId],
    ["Search", message.query],
    [
      "Matches",
      typeof message.resultCount === "number" ? String(message.resultCount) : undefined,
    ],
    ["Labels", messageValueList(message.labels)],
  ].filter((row): row is [string, string] => Boolean(row[1]));
  const body = message.bodyPreview || message.snippet;

  return (
    <div className="border-t border-border px-4 py-4">
      {rows.length > 0 && (
        <dl className="grid gap-1.5 text-[12px]">
          {rows.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="truncate font-medium text-foreground" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {body && (
        <p className="mt-3 line-clamp-4 rounded-md bg-muted/40 px-3 py-2 text-[12px] leading-5 text-muted-foreground">
          {body}
        </p>
      )}
    </div>
  );
}

function DeleteArtifactButton({
  label,
  disabled,
  onDelete,
}: {
  label: string;
  disabled: boolean;
  onDelete: () => void;
}) {
  return (
    <button
      type="button"
      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
      onClick={onDelete}
      disabled={disabled}
      aria-label={label}
      title="Delete"
    >
      <Trash2 className="h-3.5 w-3.5" />
    </button>
  );
}

function SheetsArtifactCard({
  item,
  deleting,
  selectable,
  selected,
  onToggleSelect,
  onDelete,
}: {
  item: SheetArtifactItem;
  deleting: boolean;
  selectable: boolean;
  selected: boolean;
  onToggleSelect: (item: SheetArtifactItem) => void;
  onDelete: (item: SheetArtifactItem) => void;
}) {
  const title = item.title ?? (item.sheetName ? `${item.sheetName} sheet` : "Google Sheet");
  const detailParts = [
    item.sheetName ? `Sheet: ${item.sheetName}` : undefined,
    item.range ? `Range: ${item.range}` : undefined,
  ].filter(Boolean);

  return (
    <article
      onClick={selectable ? () => onToggleSelect(item) : undefined}
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-card text-foreground",
        selectable && "cursor-pointer",
        selectable && selected && "ring-2 ring-conduut-500"
      )}
    >
      <div className="flex items-start justify-between gap-3 px-4 py-4">
        <div className="flex min-w-0 items-start gap-3">
          {selectable && (
            <Checkbox
              checked={selected}
              onCheckedChange={() => onToggleSelect(item)}
              onClick={(event) => event.stopPropagation()}
              aria-label={`Select ${title}`}
              className="mt-1"
            />
          )}
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
            <ServiceLogo service="google_sheets" className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">Google Sheets</span>
              <span className="text-muted-foreground/50">/</span>
              <span>{originSummary(item.originKinds)}</span>
              <span className="text-muted-foreground/50">/</span>
              <span>{formatDateTime(item.latestAt)}</span>
            </div>
            <h2 className="truncate text-[15px] font-medium">{title}</h2>
            <p className="mt-0.5 line-clamp-2 text-[12px] leading-5 text-muted-foreground">
              {detailParts.length > 0
                ? detailParts.join(" / ")
                : "Small preview captured from this spreadsheet."}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-muted"
            >
              Open
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          {!selectable && (
            <DeleteArtifactButton
              label={`Delete ${title}`}
              disabled={deleting}
              onDelete={() => onDelete(item)}
            />
          )}
        </div>
      </div>

      {item.previewTable ? (
        <PreviewTable table={item.previewTable} />
      ) : (
        <div className="border-t border-border px-4 py-5 text-[13px] text-muted-foreground">
          Data preview has not been captured yet. Open the Sheet to inspect the full file.
        </div>
      )}

      <div className="flex min-w-0 flex-wrap items-center gap-2 border-t border-border bg-muted/25 px-4 py-2 text-[11px] text-muted-foreground">
        <Table2 className="h-3.5 w-3.5" />
        <span>
          {item.previewTable
            ? `Showing ${Math.min(item.previewTable.rows.length, 4)} preview row(s)`
            : "Spreadsheet resource"}
        </span>
        {item.spreadsheetId && (
          <>
            <span className="text-muted-foreground/50">/</span>
            <span className="truncate" title={item.spreadsheetId}>
              ID {item.spreadsheetId}
            </span>
          </>
        )}
      </div>
    </article>
  );
}

function GenericArtifactCard({
  item,
  deleting,
  selectable,
  selected,
  onToggleSelect,
  onDelete,
}: {
  item: GenericArtifactItem;
  deleting: boolean;
  selectable: boolean;
  selected: boolean;
  onToggleSelect: (item: GenericArtifactItem) => void;
  onDelete: (item: GenericArtifactItem) => void;
}) {
  const artifact = item.artifact;
  const previewTable = tableHasPreviewData(artifact.table) ? artifact.table : undefined;
  const messagePreview =
    artifact.message && Object.keys(artifact.message).length > 0 ? artifact.message : undefined;

  return (
    <article
      onClick={selectable ? () => onToggleSelect(item) : undefined}
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-card text-foreground",
        selectable && "cursor-pointer",
        selectable && selected && "ring-2 ring-conduut-500"
      )}
    >
      <div className="flex items-start justify-between gap-3 px-4 py-4">
        <div className="flex min-w-0 items-start gap-3">
          {selectable && (
            <Checkbox
              checked={selected}
              onCheckedChange={() => onToggleSelect(item)}
              onClick={(event) => event.stopPropagation()}
              aria-label={`Select ${artifact.title}`}
              className="mt-1"
            />
          )}
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
            <ServiceLogo service={artifact.service} className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="mb-1.5 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">{serviceLabel(artifact.service)}</span>
              <span className="text-muted-foreground/50">/</span>
              <span>{originLabel(artifact.origin)}</span>
              <span className="text-muted-foreground/50">/</span>
              <span>{formatDateTime(artifact.createdAt)}</span>
            </div>
            <h2 className="truncate text-[15px] font-medium">{artifact.title}</h2>
            {artifact.description && (
              <p className="mt-0.5 line-clamp-2 text-[12px] leading-5 text-muted-foreground">
                {artifact.description}
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {artifact.url && (
            <a
              href={artifact.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-muted"
            >
              Open
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          {!selectable && (
            <DeleteArtifactButton
              label={`Delete ${artifact.title}`}
              disabled={deleting}
              onDelete={() => onDelete(item)}
            />
          )}
        </div>
      </div>
      {messagePreview ? (
        <MessagePreview message={messagePreview} />
      ) : previewTable ? (
        <PreviewTable table={previewTable} />
      ) : (
        <div className="border-t border-border px-4 py-5 text-[13px] text-muted-foreground">
          Preview is available in the source app.
        </div>
      )}
      {artifact.service === "gmail" && (
        <div className="flex min-w-0 flex-wrap items-center gap-2 border-t border-border bg-muted/25 px-4 py-2 text-[11px] text-muted-foreground">
          <Mail className="h-3.5 w-3.5" />
          <span>Gmail message preview</span>
          {messagePreview?.messageId && (
            <>
              <span className="text-muted-foreground/50">/</span>
              <span className="truncate" title={messagePreview.messageId}>
                ID {messagePreview.messageId}
              </span>
            </>
          )}
        </div>
      )}
    </article>
  );
}

export default function ArtifactsPage() {
  const { user, loading: authLoading } = useAuth();
  const confirm = useConfirm();
  const selection = useMultiSelect();
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [serviceFilter, setServiceFilter] = useState<ServiceFilter>("all");
  const [deletingIds, setDeletingIds] = useState<Set<string>>(() => new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  const queryString = useMemo(() => {
    const params = new URLSearchParams({ limit: "50" });
    if (serviceFilter !== "all") {
      params.set("service", serviceFilter);
    }
    return params.toString();
  }, [serviceFilter]);

  const loadArtifacts = useCallback(async () => {
    if (authLoading) return;
    if (!user) {
      setArtifacts([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/artifacts?${queryString}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Artifacts could not be loaded."));
      }
      const data = (await response.json()) as { artifacts?: ArtifactRecord[] };
      setArtifacts(data.artifacts ?? []);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Artifacts could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [authLoading, queryString, user]);

  useEffect(() => {
    void loadArtifacts();
  }, [loadArtifacts]);

  const dashboardItems = useMemo(() => buildDashboardItems(artifacts), [artifacts]);

  const runDelete = async (artifactIds: string[]) => {
    if (!user || artifactIds.length === 0) return;
    const previous = artifacts;
    setDeletingIds((current) => new Set([...current, ...artifactIds]));
    setArtifacts((current) => current.filter((artifact) => !artifactIds.includes(artifact.id)));
    try {
      const token = await user.getIdToken();
      const results = await Promise.allSettled(
        artifactIds.map((artifactId) =>
          fetch(`/api/artifacts/${encodeURIComponent(artifactId)}`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${token}` },
          }).then((response) => {
            if (!response.ok) throw new Error("Delete failed");
          })
        )
      );
      const failures = results.filter((result) => result.status === "rejected").length;
      if (failures > 0) {
        setArtifacts(previous);
        void loadArtifacts(); // resync truth from server
        toast.error(`${artifactIds.length - failures} deleted, ${failures} failed.`);
      } else {
        toast.success(artifactIds.length > 1 ? "Artifact previews deleted." : "Artifact deleted.");
      }
    } catch (error) {
      setArtifacts(previous);
      toast.error(error instanceof Error ? error.message : "Artifact could not be deleted.");
    } finally {
      setDeletingIds((current) => {
        const next = new Set(current);
        artifactIds.forEach((artifactId) => next.delete(artifactId));
        return next;
      });
    }
  };

  const deleteArtifacts = async (artifactIds: string[], title: string) => {
    if (!user || artifactIds.length === 0) return;
    const confirmed = await confirm({
      title: artifactIds.length > 1 ? "Delete artifact previews?" : "Delete artifact?",
      description:
        artifactIds.length > 1
          ? `"${title}" has ${artifactIds.length} saved previews. They will be removed from Conduut.`
          : `"${title}" will be removed from Conduut.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      tone: "danger",
    });
    if (!confirmed) return;
    await runDelete(artifactIds);
  };

  const handleBulkDelete = async () => {
    const selectedItems = dashboardItems.filter((item) => selection.isSelected(item.key));
    const ids = selectedItems.flatMap(itemArtifactIds);
    if (ids.length === 0) return;
    const confirmed = await confirm({
      title: "Delete artifacts?",
      description: `${ids.length} artifact preview(s) across ${selectedItems.length} card(s) will be removed from Conduut.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      tone: "danger",
    });
    if (!confirmed) return;
    setBulkDeleting(true);
    await runDelete(ids);
    setBulkDeleting(false);
    selection.exit();
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-medium text-foreground">Artifacts</h1>
        <Link href="/chat">
          <Button size="sm" className="gap-1.5">
            <MessageSquare className="h-4 w-4" />
            New in Chat
          </Button>
        </Link>
      </div>

      <div className="mb-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1">
          {FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => setServiceFilter(filter.value)}
              className={`rounded-md px-3 py-1 text-[13px] font-medium transition-colors ${
                serviceFilter === filter.value
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <Button
          type="button"
          variant={selection.selecting ? "default" : "outline"}
          size="sm"
          onClick={() => (selection.selecting ? selection.exit() : selection.enter())}
          disabled={dashboardItems.length === 0}
          className="gap-1.5"
        >
          <CheckSquare className="h-4 w-4" />
          {selection.selecting ? "Done" : "Select"}
        </Button>
      </div>

      {selection.selecting && (
        <BulkActionBar
          count={selection.selectedCount}
          total={dashboardItems.length}
          allSelected={dashboardItems.length > 0 && selection.selectedCount === dashboardItems.length}
          busy={bulkDeleting}
          onSelectAll={() => selection.selectAll(dashboardItems.map((item) => item.key))}
          onClear={selection.clear}
          onCancel={selection.exit}
          onDelete={() => void handleBulkDelete()}
        />
      )}

      {loading ? (
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      ) : artifacts.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {dashboardItems.map((item) =>
            item.kind === "sheet" ? (
              <SheetsArtifactCard
                key={item.key}
                item={item}
                deleting={item.artifactIds.some((artifactId) => deletingIds.has(artifactId))}
                selectable={selection.selecting}
                selected={selection.isSelected(item.key)}
                onToggleSelect={(sheetItem) => selection.toggle(sheetItem.key)}
                onDelete={(sheetItem) =>
                  void deleteArtifacts(sheetItem.artifactIds, sheetItem.title ?? "Google Sheet")
                }
              />
            ) : (
              <GenericArtifactCard
                key={item.key}
                item={item}
                deleting={deletingIds.has(item.artifact.id)}
                selectable={selection.selecting}
                selected={selection.isSelected(item.key)}
                onToggleSelect={(genericItem) => selection.toggle(genericItem.key)}
                onDelete={(genericItem) =>
                  void deleteArtifacts([genericItem.artifact.id], genericItem.artifact.title)
                }
              />
            )
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-muted">
            <FileSearch className="h-8 w-8 text-muted-foreground" />
          </div>
          <h2 className="mb-1 text-[16px] font-medium text-foreground">
            No artifacts yet
          </h2>
          <p className="mb-6 max-w-sm text-[14px] text-muted-foreground">
            Run a Sheets or Gmail action from chat to keep a small result preview here.
          </p>
          <Link href="/chat">
            <Button size="sm">
              <MessageSquare className="h-4 w-4" />
              Open Chat
            </Button>
          </Link>
        </div>
      )}
    </div>
  );
}
