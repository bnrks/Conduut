export type ConnectionStatus = "connected" | "expired" | "error";

export interface Connection {
  id: string;
  provider?: string;
  service?: string;
  serviceName: string;
  serviceIcon: string;
  accountEmail?: string;
  status: ConnectionStatus;
  connectedAt: string;
  updatedAt?: string;
  scopes?: string[];
  capabilities?: string[];
  permissionPacks?: string[];
  directApiEnabled?: boolean;
  missingRecommendedCapabilities?: string[];
}

export interface AvailableService {
  name: string;
  slug: string;
  icon: string;
  description: string;
  category: string;
  connectionId: string;
  authorizePath: string;
}
