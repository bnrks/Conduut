"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Logo } from "@/components/ui/logo";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { DASHBOARD_NAV } from "@/config/navigation";
import { useUIStore } from "@/lib/stores/ui-store";
import { cn } from "@/lib/utils";

const MOCK_USER = {
  name: "Burak",
  email: "burak@example.com",
  planTier: "starter" as const,
};

export function Sidebar() {
  const pathname = usePathname();
  const { sidebarCollapsed, toggleSidebar } = useUIStore();

  return (
    <motion.aside
      animate={{ width: sidebarCollapsed ? 64 : 256 }}
      transition={{ duration: 0.2, ease: "easeInOut" }}
      className="relative flex flex-col h-full border-r border-border bg-card shrink-0 overflow-hidden"
    >
      {/* Logo */}
      <div className="flex h-14 items-center px-4 shrink-0">
        <Link href="/" className="flex items-center gap-2 min-w-0">
          <Logo variant="icon" className="h-8 w-8 shrink-0" />
          <AnimatePresence>
            {!sidebarCollapsed && (
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.15, ease: "easeInOut" }}
                className="overflow-hidden"
              >
                <Logo variant="full" className="h-6 shrink-0" />
              </motion.div>
            )}
          </AnimatePresence>
        </Link>
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 overflow-y-auto">
        <ul className="flex flex-col gap-0.5">
          {DASHBOARD_NAV.map((item) => {
            const isActive =
              item.href === "/chat"
                ? pathname.startsWith("/chat")
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-[14px] font-medium transition-colors duration-150",
                    isActive
                      ? "bg-conduut-50 text-conduut-700"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                  title={sidebarCollapsed ? item.label : undefined}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0",
                      isActive ? "text-conduut-500" : ""
                    )}
                  />
                  <AnimatePresence>
                    {!sidebarCollapsed && (
                      <motion.span
                        initial={{ opacity: 0, width: 0 }}
                        animate={{ opacity: 1, width: "auto" }}
                        exit={{ opacity: 0, width: 0 }}
                        transition={{ duration: 0.15 }}
                        className="overflow-hidden whitespace-nowrap"
                      >
                        {item.label}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <Separator />

      {/* User section */}
      <div className="px-2 py-3 shrink-0">
        <div
          className={cn(
            "flex items-center gap-3 rounded-lg px-2 py-2",
            sidebarCollapsed ? "justify-center" : ""
          )}
        >
          <Avatar
            size="sm"
            fallback={MOCK_USER.name[0]}
            className="shrink-0"
          />
          <AnimatePresence>
            {!sidebarCollapsed && (
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.15 }}
                className="min-w-0 overflow-hidden"
              >
                <p className="text-[13px] font-medium text-foreground truncate whitespace-nowrap">
                  {MOCK_USER.name}
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <Badge variant="default" className="text-[11px] px-1.5 py-0">
                    {MOCK_USER.planTier}
                  </Badge>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

    </motion.aside>
  );
}
