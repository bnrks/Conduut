import type { Metadata } from "next";
import Link from "next/link";
import { Zap, Workflow, MessageSquare, Plug, ArrowUpRight } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UsageMeter } from "@/components/dashboard/usage-meter";
import { PLAN_DETAILS } from "@/lib/constants";

export const metadata: Metadata = {
  title: "Usage",
};

const MOCK_USAGE = {
  workflows: 5,
  executions: 2340,
  messages: 128,
  connections: 3,
};

const CURRENT_PLAN = "starter" as const;

export default function UsagePage() {
  const plan = PLAN_DETAILS[CURRENT_PLAN];

  return (
    <div>
      <h1 className="text-2xl font-medium text-foreground mb-6">Usage</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {/* Workflows */}
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-conduut-50">
                <Workflow className="h-4 w-4 text-conduut-500" />
              </div>
              <span className="text-[13px] text-muted-foreground">
                Workflows
              </span>
            </div>
            <p className="text-2xl font-medium tabular-nums text-foreground mb-3">
              {MOCK_USAGE.workflows}
              <span className="text-[16px] text-muted-foreground font-normal">
                /{plan.workflows}
              </span>
            </p>
            <UsageMeter
              label=""
              current={MOCK_USAGE.workflows}
              max={plan.workflows}
            />
          </CardContent>
        </Card>

        {/* Executions */}
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-conduut-50">
                <Zap className="h-4 w-4 text-conduut-500" />
              </div>
              <span className="text-[13px] text-muted-foreground">
                Executions
              </span>
            </div>
            <p className="text-2xl font-medium tabular-nums text-foreground mb-3">
              {MOCK_USAGE.executions.toLocaleString()}
              <span className="text-[16px] text-muted-foreground font-normal">
                /{plan.executionsMonthly.toLocaleString()}
              </span>
            </p>
            <UsageMeter
              label=""
              current={MOCK_USAGE.executions}
              max={plan.executionsMonthly}
            />
          </CardContent>
        </Card>

        {/* Messages */}
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-conduut-50">
                <MessageSquare className="h-4 w-4 text-conduut-500" />
              </div>
              <span className="text-[13px] text-muted-foreground">
                AI Messages
              </span>
            </div>
            <p className="text-2xl font-medium tabular-nums text-foreground mb-3">
              {MOCK_USAGE.messages}
            </p>
            <p className="text-[12px] text-muted-foreground">No limit</p>
          </CardContent>
        </Card>

        {/* Connections */}
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-conduut-50">
                <Plug className="h-4 w-4 text-conduut-500" />
              </div>
              <span className="text-[13px] text-muted-foreground">
                Connections
              </span>
            </div>
            <p className="text-2xl font-medium tabular-nums text-foreground mb-3">
              {MOCK_USAGE.connections}
              <span className="text-[16px] text-muted-foreground font-normal">
                /
                {plan.connections === "unlimited"
                  ? "∞"
                  : plan.connections}
              </span>
            </p>
            <UsageMeter
              label=""
              current={MOCK_USAGE.connections}
              max={
                plan.connections === "unlimited"
                  ? undefined
                  : plan.connections
              }
            />
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Current plan */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-medium text-foreground">
                Current Plan
              </h2>
              <Badge variant="default">{plan.name}</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-medium tabular-nums text-foreground mb-1">
              ${plan.price}
              <span className="text-[14px] text-muted-foreground font-normal">
                /mo
              </span>
            </p>
            <ul className="mt-4 flex flex-col gap-2 text-[13px] text-muted-foreground mb-6">
              <li className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-conduut-500 shrink-0" />
                {plan.workflows} workflows
              </li>
              <li className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-conduut-500 shrink-0" />
                {plan.executionsMonthly.toLocaleString()} executions/mo
              </li>
              <li className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-conduut-500 shrink-0" />
                {plan.connections === "unlimited"
                  ? "Unlimited"
                  : plan.connections}{" "}
                connected services
              </li>
            </ul>
            <Link href="/#pricing">
              <Button size="sm" className="w-full gap-1.5">
                <ArrowUpRight className="h-4 w-4" />
                Upgrade Plan
              </Button>
            </Link>
          </CardContent>
        </Card>

        {/* Execution history lives on the real Runs page. */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[15px] font-medium text-foreground">Workflow runs</h2>
                <p className="mt-1 text-[13px] text-muted-foreground">
                  Inspect successful and failed workflow runs in one place.
                </p>
              </div>
              <Link href="/dashboard/runs">
                <Button size="sm" variant="outline" className="gap-1.5">
                  View runs
                  <ArrowUpRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent className="pt-3">
            <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 px-6 text-center">
              <p className="max-w-md text-[13px] text-muted-foreground">
                Usage totals remain here; run-level status, timing, and failure details are
                shown on the Runs page.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
