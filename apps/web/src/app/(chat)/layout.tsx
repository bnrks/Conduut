"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ConversationSidebar } from "@/components/chat/conversation-sidebar";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <ConversationSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar with back button */}
        <div className="flex h-12 items-center gap-3 border-b border-border px-4 shrink-0">
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
