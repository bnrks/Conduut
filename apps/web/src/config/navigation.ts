import {
  MessageSquare,
  Workflow,
  Files,
  Plug,
  KeyRound,
  BarChart3,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const DASHBOARD_NAV: NavItem[] = [
  { label: "Chat", href: "/chat", icon: MessageSquare },
  { label: "Workflows", href: "/dashboard/workflows", icon: Workflow },
  { label: "Artifacts", href: "/dashboard/artifacts", icon: Files },
  { label: "Connections", href: "/dashboard/connections", icon: Plug },
  { label: "Credentials", href: "/dashboard/credentials", icon: KeyRound },
  { label: "Usage", href: "/dashboard/usage", icon: BarChart3 },
  { label: "Settings", href: "/dashboard/settings", icon: Settings },
];

export const MARKETING_NAV = [
  { label: "Features", href: "#features" },
  { label: "Pricing", href: "#pricing" },
];
