export type ConnectionStatus = "connected" | "expired" | "error";

export interface Connection {
  id: string;
  serviceName: string;
  serviceIcon: string;
  accountEmail?: string;
  status: ConnectionStatus;
  connectedAt: string;
}

export interface AvailableService {
  name: string;
  slug: string;
  icon: string;
  description: string;
  category: string;
}
