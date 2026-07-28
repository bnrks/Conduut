import {
  AlertCircle,
  Check,
  CheckCheck,
  Clock3,
  KeyRound,
  Mail,
  MessageSquareText,
  RefreshCcw,
  ShieldCheck,
  Table2,
  Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const FEATURES = [
  {
    title: "AI Automation Builder",
    description:
      "Describe the job in plain language and shape the first automation draft without starting from manual setup.",
    badge: "Build",
    icon: MessageSquareText,
    accent: "from-conduut-100/80 via-conduut-50/45 to-white",
    motif: (
      <div className="rounded-[22px] border border-gray-200 bg-[#F8F8FC] p-3.5">
        <div className="flex items-start gap-2.5">
          <div className="rounded-2xl bg-white px-2.5 py-1.5 text-[11px] font-medium text-gray-500 shadow-sm">
            Request
          </div>
          <div className="flex-1 rounded-[18px] bg-white px-3 py-2.5 text-[12px] leading-5 text-charcoal shadow-sm">
            Check the pricing page each weekday morning and notify me if it
            changes.
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2 text-[11px] text-conduut-700">
          <span className="h-2 w-2 rounded-full bg-conduut-500" />
          Draft prepared and kept editable
        </div>
      </div>
    ),
    points: [
      "Start from the outcome, not configuration",
      "Keep the draft editable after creation",
    ],
    footnote: "Editable after creation",
  },
  {
    title: "Integrations",
    description:
      "Work across Google Workspace, HTTP APIs, and credential-backed services with access added only where the automation needs it.",
    badge: "Connections",
    icon: KeyRound,
    accent: "from-violet-100/75 via-violet-50/40 to-white",
    motif: (
      <div className="rounded-[22px] border border-gray-200 bg-[#FBFAFF] p-3.5">
        <div className="grid grid-cols-3 gap-2 text-center text-[11px] font-medium text-gray-600">
          <div className="rounded-2xl border border-white bg-white px-2 py-2 shadow-sm">
            Gmail
          </div>
          <div className="rounded-2xl border border-white bg-white px-2 py-2 shadow-sm">
            Sheets
          </div>
          <div className="rounded-2xl border border-white bg-white px-2 py-2 shadow-sm">
            HTTP API
          </div>
        </div>
        <div className="mt-3 rounded-[18px] border border-white bg-white px-3 py-2.5 text-[12px] text-gray-600 shadow-sm">
          Missing credentials are surfaced before live action.
        </div>
      </div>
    ),
    points: [
      "Connection state stays visible in context",
      "Credentials are requested only when needed",
    ],
    footnote: "Access only when needed",
  },
  {
    title: "Safe/Fast Checks",
    description:
      "Readiness and preview policy stay explicit before anything live happens, with Safe and Fast visible as distinct operating modes.",
    badge: "Verify",
    icon: ShieldCheck,
    accent: "from-sky-100/75 via-sky-50/35 to-white",
    motif: (
      <div className="rounded-[22px] border border-gray-200 bg-[#F7FAFF] p-3.5">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-[11px] font-medium text-gray-500">Policy</p>
            <p className="mt-1 text-[12px] font-medium text-charcoal">
              Safe selected
            </p>
          </div>
          <div className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-[11px] font-medium text-sky-700">
            Fast visible
          </div>
        </div>
        <div className="mt-3 space-y-2">
          {["Connections checked", "Readiness reviewed"].map((item) => (
            <div
              key={item}
              className="flex items-center justify-between rounded-2xl border border-white bg-white px-3 py-2 text-[12px] text-gray-700 shadow-sm"
            >
              <span>{item}</span>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                Ready
              </span>
            </div>
          ))}
        </div>
      </div>
    ),
    points: [
      "Preview status is visible before the real run",
      "No hidden claim that live work already happened",
    ],
    footnote: "Checks before live action",
  },
  {
    title: "Approval Controls",
    description:
      "Sends, writes, and updates stay behind a structured approval step so live effects happen deliberately instead of by default.",
    badge: "Control",
    icon: CheckCheck,
    accent: "from-emerald-100/75 via-emerald-50/35 to-white",
    motif: (
      <div className="rounded-[22px] border border-gray-200 bg-[#FAFCFA] p-3.5">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-[11px] font-medium text-gray-500">Live action</p>
            <p className="mt-1 text-[12px] font-medium text-charcoal">
              Waiting for approval
            </p>
          </div>
          <div className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-[11px] font-medium text-emerald-700">
            No side effect yet
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-2xl border border-conduut-200 bg-white px-3 py-2 text-[12px] font-medium text-conduut-700 shadow-sm">
            Approve run
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white px-3 py-2 text-[12px] text-gray-600 shadow-sm">
            Cancel
          </div>
        </div>
      </div>
    ),
    points: [
      "Live sends and writes do not fire by default",
      "The approval path stays explicit in chat",
    ],
    footnote: "No side effect before approval",
  },
  {
    title: "Results & Artifacts",
    description:
      "Review saved outputs after the run with lightweight previews for Sheets and Gmail instead of digging through raw payloads first.",
    badge: "Outputs",
    icon: Table2,
    accent: "from-amber-100/75 via-amber-50/35 to-white",
    motif: (
      <div className="rounded-[22px] border border-gray-200 bg-[#FFFBF4] p-3.5">
        <div className="grid gap-2">
          <div className="rounded-2xl border border-white bg-white px-3 py-2.5 text-[12px] shadow-sm">
            <div className="flex items-center gap-2 text-gray-700">
              <Table2 className="h-3.5 w-3.5 text-amber-700" />
              Sheet preview saved
            </div>
          </div>
          <div className="rounded-2xl border border-white bg-white px-3 py-2.5 text-[12px] shadow-sm">
            <div className="flex items-center gap-2 text-gray-700">
              <Mail className="h-3.5 w-3.5 text-amber-700" />
              Email preview available
            </div>
          </div>
        </div>
      </div>
    ),
    points: [
      "Saved outputs remain available after the run",
      "Artifact previews help review without extra searching",
    ],
    footnote: "Saved for later review",
  },
  {
    title: "Run History & Recovery",
    description:
      "Track status, timing, and error detail after execution, then hand the exact run back into chat for targeted recovery with Conduut.",
    badge: "Recovery",
    icon: RefreshCcw,
    accent: "from-rose-100/70 via-rose-50/35 to-white",
    motif: (
      <div className="rounded-[22px] border border-gray-200 bg-[#FFF8F8] p-3.5">
        <div className="flex items-center justify-between gap-2 rounded-2xl border border-white bg-white px-3 py-2.5 shadow-sm">
          <div>
            <p className="text-[11px] font-medium text-gray-500">Run status</p>
            <p className="mt-1 text-[12px] font-medium text-charcoal">
              Failed in 12s
            </p>
          </div>
          <AlertCircle className="h-4 w-4 text-rose-600" />
        </div>
        <div className="mt-3 flex items-center justify-between gap-2 rounded-2xl border border-white bg-white px-3 py-2.5 text-[12px] text-gray-700 shadow-sm">
          <span>Fix with Conduut</span>
          <Wrench className="h-3.5 w-3.5 text-rose-600" />
        </div>
      </div>
    ),
    points: [
      "Status and timing remain visible after execution",
      "Error detail can be handed back for targeted repair",
    ],
    footnote: "Repair from the exact run",
  },
] as const;

export function Features() {
  return (
    <section
      id="features"
      className="relative scroll-mt-16 overflow-hidden bg-gray-50 py-16 sm:py-20"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-[#111218] via-[#1A1C24]/35 to-transparent"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-24 h-24 bg-gradient-to-b from-white/92 to-transparent"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-24 h-64 w-[min(62rem,94vw)] -translate-x-1/2 rounded-full bg-conduut-100/45 blur-3xl"
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-[12px] font-medium uppercase tracking-[0.28em] text-conduut-600/90">
            Features
          </p>
          <h2 className="mt-3 text-3xl font-medium tracking-tight text-charcoal sm:text-4xl">
            Capabilities that keep automation visible and controlled.
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-[15px] leading-7 text-gray-600 sm:text-[16px]">
            From the first request to run recovery, each part of the workflow
            stays reviewable instead of disappearing behind setup screens.
          </p>
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {FEATURES.map((feature) => {
            const Icon = feature.icon;

            return (
              <article
                key={feature.title}
                className="relative flex min-h-[27rem] flex-col overflow-hidden rounded-[28px] border border-gray-200 bg-white shadow-[0_24px_64px_-46px_rgba(24,24,27,0.24)]"
              >
                <div
                  aria-hidden="true"
                  className={cn(
                    "pointer-events-none absolute inset-0 bg-gradient-to-br",
                    feature.accent
                  )}
                />

                <div className="relative flex h-full flex-col p-5 sm:p-6">
                  <div className="flex items-start justify-between gap-3">
                    <Badge
                      variant="outline"
                      className="border-gray-200 bg-white/90 px-2.5 py-1 text-[11px] text-gray-600"
                    >
                      {feature.badge}
                    </Badge>
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-white/90 bg-white/92 text-charcoal shadow-sm">
                      <Icon className="h-5 w-5" />
                    </div>
                  </div>

                  <div className="mt-4">
                    <h3 className="text-[21px] font-medium leading-tight text-charcoal">
                      {feature.title}
                    </h3>
                    <p className="mt-3 text-[14px] leading-6 text-gray-600">
                      {feature.description}
                    </p>
                  </div>

                  <div className="mt-5">{feature.motif}</div>

                  <div className="mt-5 space-y-2.5">
                    {feature.points.map((point) => (
                      <div
                        key={point}
                        className="flex items-start gap-2.5 rounded-2xl border border-white/85 bg-white/90 px-3.5 py-3 text-[13px] leading-6 text-gray-700 shadow-sm"
                      >
                        <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-conduut-600 shadow-sm">
                          <Check className="h-3.5 w-3.5" />
                        </span>
                        <span>{point}</span>
                      </div>
                    ))}
                  </div>

                  <div className="mt-auto pt-5">
                    <div className="flex items-center gap-2 text-[12px] font-medium text-gray-500">
                      <Clock3 className="h-3.5 w-3.5 text-gray-400" />
                      {feature.footnote}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
