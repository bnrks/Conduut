import { ExternalLink, Table2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ArtifactPreviewData, ArtifactPreviewRow } from "@/types/artifact";

export interface ArtifactPreviewProps {
  data: ArtifactPreviewData;
  className?: string;
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

export function ArtifactPreview({ data, className }: ArtifactPreviewProps) {
  const table = data.table;
  const hasRows = Boolean(table?.columns.length && table.rows.length);

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
            <Table2 className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium">{data.title}</p>
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

      {hasRows && table ? (
        <div className="max-w-full overflow-x-auto">
          <table className="min-w-full table-fixed border-collapse text-left text-[12px]">
            <thead className="bg-muted/60 text-muted-foreground">
              <tr>
                {table.columns.map((column, columnIndex) => (
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
              {table.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b border-border/70 last:border-0">
                  {table.columns.map((column, columnIndex) => (
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
          Preview is available in Google Sheets.
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
