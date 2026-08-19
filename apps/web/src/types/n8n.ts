export type N8nConnectionStatus =
  | "connected"
  | "disconnected"
  | "checking"
  | "auth_invalid"
  | "unreachable"
  | "unsupported"
  | "error"
  | string;

export interface N8nInstance {
  id?: string;
  displayName: string;
  displayHost?: string;
  webhookBaseUrl?: string;
  ownership?: string;
  provider?: string;
  connectionStatus: N8nConnectionStatus;
  compatibilityStatus?: string;
  detectedVersion?: string;
  capabilities: string[];
  lastErrorCode?: string | null;
  lastErrorMessage?: string | null;
  verifiedAt?: string | null;
  lastHealthAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface N8nInstanceCheckResult {
  displayName?: string;
  displayHost?: string;
  connectionStatus: N8nConnectionStatus;
  compatibilityStatus?: string;
  detectedVersion?: string;
  capabilities: string[];
  verifiedAt?: string | null;
  lastErrorCode?: string | null;
  lastErrorMessage?: string | null;
  message?: string | null;
}

export interface N8nMigrationState {
  status: string;
  message?: string | null;
  totalWorkflows?: number | null;
  migratedWorkflows?: number | null;
  adoptedWorkflows?: number | null;
  remainingWorkflows?: number | null;
  nextAction?: string | null;
  canStart?: boolean;
  canAdvance?: boolean;
  updatedAt?: string | null;
}

export interface N8nSetupGuideCommand {
  description: string;
  command: string;
}

export interface N8nSetupGuideFile {
  path: string;
  description: string;
  content: string;
}

export interface N8nSetupGuideQuestion {
  field: string;
  question: string;
}

export interface N8nSetupGuideSupportedTarget {
  os: string;
  preferredOs: string;
  supportedOsVersions: string[];
  architecture: string;
  hosting: string;
  dns: string;
  ports: string;
  baselineResources: string;
  n8nVersion: string;
}

export interface N8nSetupGuideStage {
  schemaVersion: string;
  source: string;
  stage: string;
  stageIndex: number;
  totalStages: number;
  title: string;
  summary: string;
  instructions: string[];
  commands: N8nSetupGuideCommand[];
  files: N8nSetupGuideFile[];
  expectedSignals: string[];
  troubleshooting: string[];
  safetyNotes: string[];
  askFor?: N8nSetupGuideQuestion | null;
  waitForPastedOutput: boolean;
  nextStage?: string | null;
}

export interface N8nSetupGuidePayload {
  schemaVersion: string;
  source: string;
  supportedTarget: N8nSetupGuideSupportedTarget;
  totalStages: number;
  stages: N8nSetupGuideStage[];
}

export function isN8nConnected(instance: N8nInstance | null | undefined): boolean {
  return instance?.connectionStatus === "connected";
}

export function isN8nConnectionIssue(status: string | null | undefined): boolean {
  return (
    status === "disconnected" ||
    status === "auth_invalid" ||
    status === "unreachable" ||
    status === "unsupported" ||
    status === "error"
  );
}
