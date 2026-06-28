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
  const { sidebarCollapsed, toggleSidebar, mobileNavOpen, setMobileNavOpen } =
    useUIStore();

  return (
    <AuthGuard mode="protected">
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Mobile drawer backdrop */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden
        />
      )}

      {/* Sidebar wrapper — relative (NO z-index: must not create a stacking context,
          else the mobile drawer's fixed z-40 gets trapped below the z-30 backdrop).
          The toggle button carries its own z-30 to sit above the main content. */}
      <div className="relative shrink-0">
        <Sidebar />

        {/* Floating circular toggle — desktop only (sidebar is a drawer below lg) */}
        <button
          onClick={toggleSidebar}
          className="absolute top-[3.25rem] -right-3 z-30 hidden h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm hover:bg-muted hover:text-foreground transition-colors lg:flex"
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
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</main>
      </div>
    </div>
    </AuthGuard>
  );
}
