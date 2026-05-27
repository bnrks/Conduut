"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ExternalLink, FileSearch, MessageSquare, Table2 } from "lucide-react";
import { toast } from "sonner";

import { ServiceLogo } from "@/components/dashboard/service-logo";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import type {
  ArtifactPreviewRow,
  ArtifactPreviewTable,
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
        artifactCount: 0,
        latestAt: artifact.createdAt,
        latestTime,
        originKinds: [],
        previewTime: 0,
      } satisfies SheetArtifactItem);

    current.artifactCount += 1;
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

function SheetsArtifactCard({ item }: { item: SheetArtifactItem }) {
  const title = item.title ?? (item.sheetName ? `${item.sheetName} sheet` : "Google Sheet");
  const detailParts = [
    item.sheetName ? `Sheet: ${item.sheetName}` : undefined,
    item.range ? `Range: ${item.range}` : undefined,
  ].filter(Boolean);

  return (
    <article className="overflow-hidden rounded-lg border border-border bg-card text-foreground">
      <div className="flex items-start justify-between gap-3 px-4 py-4">
        <div className="flex min-w-0 items-start gap-3">
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
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-muted"
          >
            Open
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
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

function GenericArtifactCard({ item }: { item: GenericArtifactItem }) {
  const artifact = item.artifact;
  const previewTable = tableHasPreviewData(artifact.table) ? artifact.table : undefined;

  return (
    <article className="overflow-hidden rounded-lg border border-border bg-card text-foreground">
      <div className="flex items-start justify-between gap-3 px-4 py-4">
        <div className="flex min-w-0 items-start gap-3">
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
        {artifact.url && (
          <a
            href={artifact.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-muted"
          >
            Open
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
      {previewTable ? (
        <PreviewTable table={previewTable} />
      ) : (
        <div className="border-t border-border px-4 py-5 text-[13px] text-muted-foreground">
          Preview is available in the source app.
        </div>
      )}
    </article>
  );
}

export default function ArtifactsPage() {
  const { user, loading: authLoading } = useAuth();
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [serviceFilter, setServiceFilter] = useState<ServiceFilter>("all");

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

      <div className="mb-6 flex items-center gap-1 rounded-lg border border-border bg-card p-1">
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

      {loading ? (
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      ) : artifacts.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {dashboardItems.map((item) => (
            item.kind === "sheet" ? (
              <SheetsArtifactCard key={item.key} item={item} />
            ) : (
              <GenericArtifactCard key={item.key} item={item} />
            )
          ))}
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
            Run a Sheets action from chat or a workflow to keep a small result preview here.
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
