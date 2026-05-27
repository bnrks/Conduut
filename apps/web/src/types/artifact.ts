export type ArtifactPreviewRow = Record<string, unknown> | unknown[];
export type ArtifactService = "google_sheets" | "gmail";
export type ArtifactPreviewType = "table_preview" | "message_preview";

export interface ArtifactPreviewTable {
  columns: string[];
  rows: ArtifactPreviewRow[];
  truncated?: boolean;
  totalRows?: number;
}

export interface ArtifactPreviewData {
  service: ArtifactService;
  title: string;
  description?: string;
  url?: string;
  source?: Record<string, unknown>;
  table?: ArtifactPreviewTable;
}

export interface ArtifactOrigin {
  kind: "chat" | "workflow_run";
  conversationId?: string;
  workflowId?: string;
  executionId?: string;
}

export interface ArtifactRecord extends ArtifactPreviewData {
  id: string;
  type: ArtifactPreviewType;
  origin: ArtifactOrigin;
  createdAt: string;
}
