export type ArtifactPreviewRow = Record<string, unknown> | unknown[];

export interface ArtifactPreviewTable {
  columns: string[];
  rows: ArtifactPreviewRow[];
  truncated?: boolean;
  totalRows?: number;
}

export interface ArtifactPreviewData {
  service: "google_sheets";
  title: string;
  description?: string;
  url?: string;
  source?: Record<string, unknown>;
  table?: ArtifactPreviewTable;
}
