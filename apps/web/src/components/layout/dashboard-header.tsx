"use client";

import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { useUIStore } from "@/lib/stores/ui-store";

const ROUTE_LABELS: Record<string, string> = {
  "/chat": "Chat",
  "/dashboard/workflows": "Workflows",
  "/dashboard/connections": "Connections",
  "/dashboard/usage": "Usage",
  "/dashboard/settings": "Settings",
};

function getBreadcrumb(pathname: string): string {
  for (const [route, label] of Object.entries(ROUTE_LABELS)) {
    if (pathname.startsWith(route)) return label;
  }
  return "Dashboard";
}

export function DashboardHeader() {
  const pathname = usePathname();
  const { toggleSidebar } = useUIStore();
  const breadcrumb = getBreadcrumb(pathname);

  return (
    <header className="h-14 border-b border-border flex items-center justify-between px-6 bg-card shrink-0">
      {/* Left */}
      <div className="flex items-center gap-3">
        <button
          onClick={toggleSidebar}
          className="md:hidden flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Toggle sidebar"
        >
          <Menu className="h-4 w-4" />
        </button>
        <div className="flex items-center gap-2 text-[14px]">
          <span className="text-muted-foreground">Dashboard</span>
          {breadcrumb !== "Dashboard" && (
            <>
              <span className="text-muted-foreground">/</span>
              <span className="font-medium text-foreground">{breadcrumb}</span>
            </>
          )}
        </div>
      </div>

      {/* Right */}
      <div className="flex items-center gap-3">
        <button
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-muted transition-colors"
          aria-label="User menu"
        >
          <Avatar size="sm" fallback="B" />
        </button>
      </div>
    </header>
  );
}
