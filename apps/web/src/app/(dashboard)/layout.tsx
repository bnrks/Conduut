"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Sidebar } from "@/components/layout/sidebar";
import { DashboardHeader } from "@/components/layout/dashboard-header";
import { AuthGuard } from "@/components/auth/auth-guard";
import { useUIStore } from "@/lib/stores/ui-store";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { sidebarCollapsed, toggleSidebar } = useUIStore();

  return (
    <AuthGuard mode="protected">
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar wrapper — relative + overflow-visible so the toggle button can poke out */}
      <div className="relative shrink-0" style={{ zIndex: 20 }}>
        <Sidebar />

        {/* Floating circular toggle — positioned on the sidebar's right edge */}
        <button
          onClick={toggleSidebar}
          className="absolute top-[3.25rem] -right-3 z-30 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm hover:bg-muted hover:text-foreground transition-colors"
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronLeft className="h-3 w-3" />
          )}
        </button>
      </div>

      {/* Main area */}
      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        <DashboardHeader />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
    </AuthGuard>
  );
}
