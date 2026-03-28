"use client";

import { Plus } from "lucide-react";
import { ConnectionCard } from "@/components/dashboard/connection-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Connection, AvailableService } from "@/types/connection";
import { cn } from "@/lib/utils";

const CONNECTED_SERVICES: Connection[] = [
  {
    id: "conn-1",
    serviceName: "Google",
    serviceIcon: "google",
    accountEmail: "burak@gmail.com",
    status: "connected",
    connectedAt: "2026-01-10T10:00:00Z",
  },
  {
    id: "conn-2",
    serviceName: "Slack",
    serviceIcon: "slack",
    accountEmail: "burak@myworkspace.slack.com",
    status: "connected",
    connectedAt: "2026-01-15T14:00:00Z",
  },
  {
    id: "conn-3",
    serviceName: "GitHub",
    serviceIcon: "github",
    accountEmail: "burak@github.com",
    status: "expired",
    connectedAt: "2025-12-01T09:00:00Z",
  },
];

const AVAILABLE_SERVICES: AvailableService[] = [
  {
    name: "Notion",
    slug: "notion",
    icon: "notion",
    description: "Connect your Notion workspace",
    category: "Productivity",
  },
  {
    name: "Discord",
    slug: "discord",
    icon: "discord",
    description: "Send messages to Discord channels",
    category: "Communication",
  },
  {
    name: "Telegram",
    slug: "telegram",
    icon: "telegram",
    description: "Send Telegram messages and alerts",
    category: "Communication",
  },
  {
    name: "Airtable",
    slug: "airtable",
    icon: "airtable",
    description: "Read and write Airtable bases",
    category: "Database",
  },
  {
    name: "Microsoft Teams",
    slug: "microsoft",
    icon: "microsoft",
    description: "Post messages in Teams channels",
    category: "Communication",
  },
  {
    name: "Trello",
    slug: "trello",
    icon: "trello",
    description: "Manage Trello boards and cards",
    category: "Productivity",
  },
];

const SERVICE_COLORS: Record<string, string> = {
  notion: "bg-gray-100 text-gray-700",
  discord: "bg-indigo-100 text-indigo-600",
  telegram: "bg-sky-100 text-sky-600",
  airtable: "bg-yellow-100 text-yellow-600",
  microsoft: "bg-blue-100 text-blue-600",
  trello: "bg-blue-100 text-blue-600",
};

export default function ConnectionsPage() {
  return (
    <div>
      <h1 className="text-2xl font-medium text-foreground mb-6">Connections</h1>

      {/* Connected services */}
      <section className="mb-8">
        <h2 className="text-[16px] font-medium text-foreground mb-3">
          Connected Services
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {CONNECTED_SERVICES.map((conn) => (
            <ConnectionCard key={conn.id} connection={conn} />
          ))}
        </div>
      </section>

      {/* Available services */}
      <section>
        <h2 className="text-[16px] font-medium text-foreground mb-3">
          Available Services
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {AVAILABLE_SERVICES.map((service) => {
            const colorClass =
              SERVICE_COLORS[service.slug] ?? "bg-conduut-50 text-conduut-700";
            return (
              <Card key={service.slug} className="opacity-80">
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[16px] font-semibold",
                        colorClass
                      )}
                    >
                      {service.name[0].toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[14px] font-medium text-foreground">
                        {service.name}
                      </p>
                      <p className="text-[12px] text-muted-foreground truncate">
                        {service.description}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-[12px] px-3 shrink-0"
                      onClick={() => console.log("Connect:", service.slug)}
                    >
                      <Plus className="h-3 w-3" />
                      Connect
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
