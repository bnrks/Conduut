import type { ReactNode } from "react";
import { ExternalLink, Mail, Table2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  ArtifactPreviewData,
  ArtifactPreviewMessage,
  ArtifactPreviewRow,
} from "@/types/artifact";

export interface ArtifactPreviewProps {
  data: ArtifactPreviewData;
  className?: string;
  metadata?: ReactNode;
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

function serviceFallback(service: ArtifactPreviewData["service"]): string {
  if (service === "gmail") return "Preview is available in Gmail.";
  return "Preview is available in Google Sheets.";
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
    <div className="border-t border-border px-3.5 py-3">
      {rows.length > 0 && (
        <dl className="grid gap-1.5 text-[12px]">
          {rows.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[64px_minmax(0,1fr)] gap-2">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="truncate font-medium text-foreground" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {body && (
        <p className="mt-2 line-clamp-3 rounded-md bg-muted/40 px-2.5 py-2 text-[12px] leading-5 text-muted-foreground">
          {body}
        </p>
      )}
    </div>
  );
}

export function ArtifactPreview({ data, className, metadata }: ArtifactPreviewProps) {
  const table = data.table;
  const message = data.message;
  const columns = Array.isArray(table?.columns) ? table.columns : [];
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  const hasRows = columns.length > 0 && rows.length > 0;
  const hasMessage = message && Object.keys(message).length > 0;
  const Icon = data.service === "gmail" ? Mail : Table2;

  return (
    <div
      className={cn(
        "mt-2 w-full overflow-hidden rounded-lg border border-border bg-card text-foreground",
        className
      )}
    >
      <div className="flex items-start justify-between gap-3 border-b border-border px-3.5 py-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-conduut-500">
            <Icon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            {metadata}
            <p className="truncate text-[13px] font-medium">
              {data.title ||
                (data.service === "gmail" ? "Gmail preview" : "Google Sheets preview")}
            </p>
            {data.description && (
              <p className="mt-0.5 line-clamp-2 text-[12px] leading-5 text-muted-foreground">
                {data.description}
              </p>
            )}
          </div>
        </div>
        {data.url && (
          <a
            href={data.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:bg-muted"
          >
            Open
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>

      {hasMessage && message ? (
        <MessagePreview message={message} />
      ) : hasRows ? (
        <div className="max-w-full overflow-x-auto">
          <table className="min-w-full table-fixed border-collapse text-left text-[12px]">
            <thead className="bg-muted/60 text-muted-foreground">
              <tr>
                {columns.map((column, columnIndex) => (
                  <th
                    key={`${column}-${columnIndex}`}
                    className="max-w-[180px] border-b border-border px-3 py-2 font-medium"
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
                    <td key={`${rowIndex}-${column}`} className="max-w-[180px] px-3 py-2">
                      <span
                        className="block truncate"
                        title={cellText(rowCell(row, column, columnIndex))}
                      >
                        {cellText(rowCell(row, column, columnIndex))}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-3.5 py-3 text-[12px] text-muted-foreground">
          {serviceFallback(data.service)}
        </div>
      )}

      {table?.truncated && (
        <div className="border-t border-border bg-muted/30 px-3.5 py-2 text-[11px] text-muted-foreground">
          Showing a preview{table.totalRows ? ` of ${table.totalRows} row(s)` : ""}.
        </div>
      )}
    </div>
  );
}
