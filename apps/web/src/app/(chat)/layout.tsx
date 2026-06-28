"use client";

import Link from "next/link";
import { ArrowLeft, Menu } from "lucide-react";
import { ConversationSidebar } from "@/components/chat/conversation-sidebar";
import { useUIStore } from "@/lib/stores/ui-store";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { mobileNavOpen, setMobileNavOpen } = useUIStore();

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Mobile drawer backdrop */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden
        />
      )}

      <ConversationSidebar />
      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        {/* Top bar with back button */}
        <div className="flex h-12 items-center gap-2 border-b border-border px-4 shrink-0">
          <button
            onClick={() => setMobileNavOpen(true)}
            className="lg:hidden flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            aria-label="Open navigation"
          >
            <Menu className="h-4 w-4" />
          </button>
          <Link
            href="/dashboard/workflows"
            className="flex items-center gap-2 text-[13px] text-muted-foreground hover:text-foreground transition-colors duration-150"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Dashboard</span>
          </Link>
        </div>
        <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
      </div>
    </div>
  );
}
