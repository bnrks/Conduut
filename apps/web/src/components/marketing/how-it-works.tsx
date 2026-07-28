"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  CheckCheck,
  MessageSquareText,
  Play,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const STAGES = [
  {
    number: "01",
    title: "Request",
    description:
      "Describe the outcome in plain language. Conduut starts from the business task, not nodes or JSON.",
    detail: "Natural-language request",
    icon: MessageSquareText,
    accent: "from-[#A871FF]/30 via-[#A871FF]/10 to-transparent",
  },
  {
    number: "02",
    title: "Draft",
    description:
      "Conduut drafts the native n8n workflow and maps reusable runtime inputs where they belong.",
    detail: "Native n8n workflow draft",
    icon: Workflow,
    accent: "from-[#9A7BFF]/26 via-[#9A7BFF]/10 to-transparent",
  },
  {
    number: "03",
    title: "Check and preview",
    description:
      "Connections, readiness, and preview policy are checked before anything live happens.",
    detail: "Readiness + Safe/Fast checks",
    icon: ShieldCheck,
    accent: "from-[#73C2FF]/24 via-[#73C2FF]/10 to-transparent",
  },
  {
    number: "04",
    title: "Approval",
    description:
      "Writes, sends, and updates stay behind a structured approval gate instead of running by default.",
    detail: "Structured approval gate",
    icon: CheckCheck,
    accent: "from-[#8DF0C7]/24 via-[#8DF0C7]/10 to-transparent",
  },
  {
    number: "05",
    title: "Run and review",
    description:
      "After approval, you can review the saved workflow, run result, artifacts, and history in one place.",
    detail: "Run result, artifacts, history",
    icon: Play,
    accent: "from-[#F6D37A]/22 via-[#F6D37A]/10 to-transparent",
  },
] as const;

export function HowItWorks() {
  const reduceMotion = useReducedMotion() ?? false;

  return (
    <section
      id="how-it-works"
      className="relative scroll-mt-16 overflow-hidden bg-[#111218] py-14 text-white sm:py-16"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(168,113,255,0.16),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(78,163,255,0.12),transparent_26%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/12 to-transparent"
      />

      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-[12px] font-medium uppercase tracking-[0.28em] text-conduut-200/90">
            How it works
          </p>
          <h2 className="mt-3 text-3xl font-medium tracking-tight text-white sm:text-4xl">
            One request, five controlled stages.
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-[15px] leading-7 text-white/68 sm:text-[16px]">
            Conduut moves from request to draft, checks, approval, and run
            review on a single visible path.
          </p>
        </div>

        <div className="relative mx-auto mt-10 max-w-5xl lg:mt-12">
          <div
            aria-hidden="true"
            className="absolute bottom-0 left-5 top-0 w-px bg-gradient-to-b from-white/0 via-white/16 to-white/0 sm:left-1/2 sm:-translate-x-1/2"
          />

          {!reduceMotion ? (
            <motion.span
              aria-hidden="true"
              className="absolute left-5 top-[8%] h-2.5 w-2.5 rounded-full border border-conduut-100/65 bg-conduut-200 shadow-[0_0_14px_rgba(171,112,255,0.5)] sm:left-1/2 sm:-translate-x-1/2"
              animate={{
                top: ["8%", "92%", "8%"],
                opacity: [0.35, 1, 0.35],
              }}
              transition={{
                duration: 8.5,
                ease: "easeInOut",
                repeat: Number.POSITIVE_INFINITY,
              }}
            />
          ) : null}

          <div className="space-y-4 sm:space-y-5">
            {STAGES.map((stage, index) => {
              const Icon = stage.icon;
              const isRightAligned = index % 2 === 1;

              return (
                <motion.article
                  key={stage.number}
                  initial={false}
                  whileInView={
                    reduceMotion
                      ? undefined
                      : {
                          opacity: [0.72, 1],
                          y: [18, 0],
                        }
                  }
                  viewport={{ once: true, margin: "-80px" }}
                  transition={{
                    duration: reduceMotion ? 0 : 0.42,
                    delay: reduceMotion ? 0 : index * 0.05,
                    ease: "easeOut",
                  }}
                  className="relative"
                >
                  <div
                    className={cn(
                      "grid gap-3 sm:grid-cols-[minmax(0,1fr)_3rem_minmax(0,1fr)] sm:gap-4",
                      isRightAligned ? "sm:[&>*:last-child]:col-start-3" : ""
                    )}
                  >
                    <div
                      className={cn(
                        "relative ml-11 min-w-0 overflow-hidden rounded-[24px] border border-white/10 bg-white/[0.045] p-4 shadow-[0_18px_40px_-30px_rgba(0,0,0,0.75)] backdrop-blur-sm sm:ml-0 sm:max-w-[28rem] sm:p-5",
                        isRightAligned ? "sm:col-start-3 sm:justify-self-start" : "sm:col-start-1 sm:justify-self-end"
                      )}
                    >
                      <div
                        aria-hidden="true"
                        className={cn(
                          "pointer-events-none absolute inset-0 bg-gradient-to-br opacity-100",
                          stage.accent
                        )}
                      />

                      <div className="relative flex items-start gap-3 sm:gap-4">
                        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-conduut-200/35 bg-conduut-400/12 text-conduut-100">
                          <Icon className="h-4.5 w-4.5" />
                        </div>

                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[11px] font-medium tracking-[0.24em] text-conduut-200/80">
                              {stage.number}
                            </span>
                            <Badge
                              variant="outline"
                              className="border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-conduut-100/92"
                            >
                              {stage.detail}
                            </Badge>
                          </div>

                          <h3 className="mt-2 text-[18px] font-medium leading-snug text-white">
                            {stage.title}
                          </h3>
                          <p className="mt-2 text-[14px] leading-6 text-white/68">
                            {stage.description}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div
                      aria-hidden="true"
                      className="absolute left-5 top-5 flex h-10 w-10 items-center justify-center sm:absolute sm:left-1/2 sm:top-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2"
                    >
                      <div className="absolute inset-[7px] rounded-full border border-white/12 bg-[#171922]" />
                      <div className="absolute inset-[11px] rounded-full bg-white/6" />
                      <div className="relative z-10 flex h-4 w-4 items-center justify-center rounded-full bg-conduut-200 shadow-[0_0_14px_rgba(171,112,255,0.45)]">
                        <Sparkles className="h-2.5 w-2.5 text-[#111218]" />
                      </div>
                    </div>
                  </div>
                </motion.article>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
