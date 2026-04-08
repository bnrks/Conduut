"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Plus, Search, PanelLeftClose, PanelLeft } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { useChatStore } from "@/lib/stores/chat-store";
import { useUIStore } from "@/lib/stores/ui-store";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/types/chat";

function groupConversationsByDate(conversations: Conversation[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400 * 1000);
  const sevenDaysAgo = new Date(today.getTime() - 86400 * 1000 * 7);

  const groups: {
    label: string;
    items: Conversation[];
  }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Older", items: [] },
  ];

  for (const conv of conversations) {
    const date = new Date(conv.lastMessageAt);
    const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    if (dateOnly >= today) {
      groups[0].items.push(conv);
    } else if (dateOnly >= yesterday) {
      groups[1].items.push(conv);
    } else if (dateOnly >= sevenDaysAgo) {
      groups[2].items.push(conv);
    } else {
      groups[3].items.push(conv);
    }
  }

  return groups.filter((g) => g.items.length > 0);
}

export function ConversationSidebar() {
  const { sidebarCollapsed, toggleSidebar } = useUIStore();
  const { conversations, setConversations } = useChatStore();
  const { user } = useAuth();
  const [search, setSearch] = useState("");
  const pathname = usePathname();

  useEffect(() => {
    const loadConversations = async () => {
      if (!user) return;

      const token = await user.getIdToken();
      const response = await fetch("/api/conversations", {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) return;

      const data = (await response.json()) as { conversations?: Conversation[] };
      setConversations(data.conversations || []);
    };

    void loadConversations();
  }, [setConversations, user, pathname]);

  const filtered = useMemo(
    () =>
      conversations.filter((c) =>
        c.title.toLowerCase().includes(search.toLowerCase())
      ),
    [conversations, search]
  );

  const grouped = groupConversationsByDate(filtered);

  return (
    <>
      {/* Sidebar */}
      <AnimatePresence initial={false}>
        {!sidebarCollapsed && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 288, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="flex flex-col border-r border-border bg-background overflow-hidden shrink-0"
          >
            <div className="flex flex-col h-full w-72">
              {/* Header */}
              <div className="flex items-center justify-between px-3 pt-3 pb-2">
                <span className="text-[13px] font-medium text-muted-foreground pl-1">
                  Conversations
                </span>
                <button
                  onClick={toggleSidebar}
                  className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-all duration-150"
                  aria-label="Collapse sidebar"
                >
                  <PanelLeftClose className="h-4 w-4" />
                </button>
              </div>

              {/* New Chat button */}
              <div className="px-3 pb-2">
                <Link href="/chat">
                  <button className="flex w-full items-center gap-2 rounded-lg bg-conduut-500 px-3 py-2 text-[13px] font-medium text-white hover:bg-conduut-700 transition-colors duration-150">
                    <Plus className="h-4 w-4" />
                    New Chat
                  </button>
                </Link>
              </div>

              {/* Search */}
              <div className="px-3 pb-2">
                <div className="flex items-center gap-2 rounded-md border border-border bg-muted px-2.5 py-1.5">
                  <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder="Search..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="flex-1 bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none"
                  />
                </div>
              </div>

              {/* Conversation list */}
              <div className="flex-1 overflow-y-auto px-2 pb-3">
                {grouped.length === 0 ? (
                  <p className="px-2 py-4 text-center text-[13px] text-muted-foreground">
                    No conversations found
                  </p>
                ) : (
                  grouped.map((group) => (
                    <div key={group.label} className="mb-3">
                      <p className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                        {group.label}
                      </p>
                      <ul className="space-y-0.5">
                        {group.items.map((conv) => {
                          const isActive = pathname === `/chat/${conv.id}`;
                          return (
                            <li key={conv.id}>
                              <Link href={`/chat/${conv.id}`}>
                                <span
                                  className={cn(
                                    "block truncate rounded-md px-2 py-1.5 text-[13px] cursor-pointer",
                                    "transition-colors duration-150",
                                    isActive
                                      ? "bg-conduut-50 text-conduut-700 font-medium"
                                      : "text-foreground hover:bg-muted"
                                  )}
                                >
                                  {conv.title}
                                </span>
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ))
                )}
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Collapsed toggle button */}
      {sidebarCollapsed && (
        <div className="flex flex-col items-center border-r border-border bg-background px-1.5 pt-3">
          <button
            onClick={toggleSidebar}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-all duration-150"
            aria-label="Expand sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        </div>
      )}
    </>
  );
}
