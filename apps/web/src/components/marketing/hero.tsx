"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowRight,
  Check,
  Circle,
  Info,
  PencilLine,
  SendHorizontal,
  ShieldCheck,
} from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Logo } from "@/components/ui/logo";
import { WorkflowPreview } from "@/components/chat/workflow-preview";
import { cn } from "@/lib/utils";

const ACTIVITY_STEPS = [
  {
    label: "Checked Gmail send and Google Sheets write access",
    tone: "default" as const,
  },
  {
    label: "Prepared the workflow draft and safe preview",
    tone: "success" as const,
  },
];

const MOTION_OFFSET = 14;
const FINAL_STAGE = 6;
const SEQUENCE_STEPS = [
  { stage: 1, delayMs: 500 },
  { stage: 2, delayMs: 700 },
  { stage: 3, delayMs: 900 },
  { stage: 4, delayMs: 950 },
  { stage: 5, delayMs: 1_050 },
  { stage: 6, delayMs: 950 },
] as const;

function theaterMotion(delay: number, reduceMotion: boolean) {
  if (reduceMotion) {
    return {
      initial: false,
      whileInView: undefined,
      transition: undefined,
      viewport: undefined,
    };
  }

  return {
    initial: { opacity: 0, y: MOTION_OFFSET },
    whileInView: { opacity: 1, y: 0 },
    transition: { duration: 0.58, delay, ease: "easeOut" as const },
    viewport: { once: true, margin: "-80px" },
  };
}

function ThinkingDots() {
  return (
    <div
      aria-label="Conduut is thinking"
      className="flex items-center gap-0.5 text-[15px] leading-none text-muted-foreground"
      role="status"
    >
      <span className="[animation:conduut-dot-blink_1.4s_infinite] motion-reduce:[animation:none]">
        .
      </span>
      <span className="[animation:conduut-dot-blink_1.4s_infinite_0.2s] motion-reduce:[animation:none]">
        .
      </span>
      <span className="[animation:conduut-dot-blink_1.4s_infinite_0.4s] motion-reduce:[animation:none]">
        .
      </span>
    </div>
  );
}

export function Hero() {
  const reduceMotion = useReducedMotion() ?? false;
  const [visibleStage, setVisibleStage] = useState(0);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const renderedStage = reduceMotion ? FINAL_STAGE : visibleStage;

  useEffect(() => {
    if (reduceMotion) {
      return;
    }

    let elapsedMs = 0;
    const timers = SEQUENCE_STEPS.map(({ stage, delayMs }) => {
      elapsedMs += delayMs;
      return window.setTimeout(() => {
        setVisibleStage(stage);
      }, elapsedMs);
    });

    return () => {
      for (const timer of timers) {
        window.clearTimeout(timer);
      }
    };
  }, [reduceMotion]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [reduceMotion, renderedStage]);

  return (
    <section className="relative overflow-hidden bg-white pt-24 pb-16 sm:pt-32 sm:pb-24">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-conduut-50/60 via-white to-white"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute top-0 left-1/2 h-[480px] w-[900px] -translate-x-1/2 rounded-full bg-conduut-100/30 blur-3xl"
      />

      <div className="relative mx-auto grid max-w-7xl gap-10 px-4 sm:px-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-center lg:gap-14 lg:px-8">
        <div className="min-w-0 max-w-2xl">
          <div className="inline-flex items-center gap-2 rounded-full border border-conduut-200 bg-conduut-50 px-3.5 py-1 text-[13px] font-medium text-conduut-700">
            <ShieldCheck className="h-3.5 w-3.5" />
            AI automation, with proof before action.
          </div>

          <h1 className="mt-6 text-4xl font-medium leading-[1.08] tracking-tight text-charcoal sm:text-5xl">
            Tell Conduut what needs to happen.
            <span className="mt-4 block text-[30px] leading-[1.12] text-conduut-500 sm:text-[38px] lg:text-[42px]">
              It builds the automation — and checks it before it acts.
            </span>
          </h1>

          <p className="mt-6 max-w-xl text-[15px] leading-7 text-gray-500 sm:text-lg sm:leading-8">
            Create, connect, preview, approve, and run n8n workflows from one
            conversation — without dropping into JSON or node setup screens.
          </p>

          <div className="mt-8 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <Link
              href="/register"
              className={cn(buttonVariants({ size: "lg" }))}
            >
              Build your first workflow
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a
              href="#how-it-works"
              className={cn(buttonVariants({ variant: "outline", size: "lg" }))}
            >
              See how it works
            </a>
          </div>

          <div className="mt-6 hidden flex-wrap gap-2.5 text-[13px] text-gray-600 sm:flex">
            <div className="rounded-full border border-gray-200 bg-white px-3 py-1.5">
              Preview before action
            </div>
            <div className="rounded-full border border-gray-200 bg-white px-3 py-1.5">
              Connect accounts only when needed
            </div>
            <div className="rounded-full border border-gray-200 bg-white px-3 py-1.5">
              n8n workflow stays editable
            </div>
          </div>
        </div>

        <motion.div
          {...theaterMotion(0.05, reduceMotion)}
          className="mx-auto flex min-w-0 w-full max-w-[42rem] lg:self-stretch"
        >
          <div className="flex h-[540px] min-h-0 w-full min-w-0 flex-col overflow-hidden rounded-[28px] border border-gray-200 bg-white shadow-[0_24px_80px_-40px_rgba(24,24,27,0.28)] sm:h-[580px] lg:h-[590px]">
            <div className="flex shrink-0 items-center justify-between border-b border-gray-100 bg-gray-50/90 px-4 py-3 sm:px-5">
              <div className="flex items-center gap-2">
                <div className="h-2.5 w-2.5 rounded-full bg-red-300" />
                <div className="h-2.5 w-2.5 rounded-full bg-yellow-300" />
                <div className="h-2.5 w-2.5 rounded-full bg-green-300" />
                <span className="ml-2 text-[12px] font-medium text-gray-400">
                  Conduut conversation
                </span>
              </div>
              <div className="rounded-full border border-conduut-200 bg-conduut-50 px-2.5 py-1 text-[11px] font-medium text-conduut-700">
                Safe mode
              </div>
            </div>

            <div className="relative flex-1 min-h-0 min-w-0">
              <div ref={viewportRef} className="h-full overflow-y-auto">
                <div className="flex min-h-full min-w-0 flex-col justify-end gap-3 p-3.5 sm:p-4">
                  {renderedStage === 0 ? (
                    <div
                      aria-hidden="true"
                      className="flex flex-1 items-center justify-center rounded-[20px] border border-dashed border-gray-200/80 bg-gray-50/55"
                    >
                      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                        <span className="h-2 w-2 rounded-full bg-conduut-400" />
                        <span>Conduut is ready for a request</span>
                      </div>
                    </div>
                  ) : null}

                  {renderedStage >= 1 ? (
                    <motion.div
                      {...theaterMotion(0.08, reduceMotion)}
                      className="flex justify-end"
                    >
                      <div className="flex max-w-[92%] min-w-0 items-start gap-2.5">
                        <div className="rounded-2xl rounded-br-md bg-conduut-50 px-4 py-3 text-[14px] leading-5 text-conduut-900">
                          <p>
                            Every weekday at 9 AM, check our pricing page. If
                            the page is down or changed, send me an email and
                            log the result in Google Sheets.
                          </p>
                        </div>
                        <Avatar
                          size="sm"
                          fallback="U"
                          className="mt-1 shrink-0 bg-gray-200 text-gray-700"
                        />
                      </div>
                    </motion.div>
                  ) : null}

                  <AnimatePresence initial={false}>
                    {renderedStage === 2 ? (
                      <motion.div
                        key="thinking"
                        initial={reduceMotion ? false : { opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={
                          reduceMotion
                            ? undefined
                            : {
                                opacity: 0,
                                y: -10,
                                transition: {
                                  duration: 0.5,
                                  ease: "easeOut",
                                },
                              }
                        }
                        className="flex justify-start"
                      >
                        <div className="flex max-w-[92%] min-w-0 items-start gap-3">
                          <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center">
                            <Logo variant="icon" className="h-8 w-8" />
                          </div>
                          <div className="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-2.5">
                            <ThinkingDots />
                          </div>
                        </div>
                      </motion.div>
                    ) : null}
                  </AnimatePresence>

                  {renderedStage >= 3 ? (
                    <motion.div
                      {...theaterMotion(0.1, reduceMotion)}
                      className="rounded-2xl border border-gray-200 bg-white p-3.5"
                    >
                      <div className="flex items-start gap-3">
                        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center">
                          <Logo variant="icon" className="h-8 w-8" />
                        </div>
                        <div className="min-h-0 min-w-0 flex-1 space-y-1.5">
                          {ACTIVITY_STEPS.map((step, index) => (
                            <motion.div
                              key={step.label}
                              initial={
                                reduceMotion ? false : { opacity: 0, y: 8 }
                              }
                              animate={{ opacity: 1, y: 0 }}
                              transition={{
                                duration: reduceMotion ? 0 : 0.32,
                                delay: reduceMotion ? 0 : index * 0.18,
                                ease: "easeOut",
                              }}
                              className="flex items-center gap-1.5 py-0.5 text-[12px] text-muted-foreground"
                            >
                              <Check
                                className={cn(
                                  "h-3 w-3",
                                  step.tone === "success"
                                    ? "text-success"
                                    : "text-conduut-500"
                                )}
                              />
                              <span>{step.label}</span>
                            </motion.div>
                          ))}
                        </div>
                      </div>
                    </motion.div>
                  ) : null}

                  {renderedStage >= 4 ? (
                    <motion.div
                      {...theaterMotion(0.1, reduceMotion)}
                      className="rounded-2xl border border-gray-200 bg-white p-3.5"
                    >
                      <div className="flex items-start gap-3">
                        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center">
                          <Logo variant="icon" className="h-8 w-8" />
                        </div>
                        <div className="min-h-0 min-w-0 flex-1">
                          <div className="max-w-[28rem] rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3 text-[14px] leading-6 text-foreground">
                            I drafted a reusable workflow for the weekday site
                            check, confirmed the required connections, and
                            prepared a safe preview. No live run has happened
                            yet.
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ) : null}

                  {renderedStage >= 5 ? (
                    <motion.div {...theaterMotion(0.1, reduceMotion)}>
                      <WorkflowPreview
                        className="min-w-0"
                        data={{
                          name: "Pricing page monitor with Gmail alert + Sheets log",
                          nodeCount: 4,
                          status: "inactive",
                          id: "wf_demo_2026",
                        }}
                      />
                    </motion.div>
                  ) : null}

                  {renderedStage >= 6 ? (
                    <motion.div
                      {...theaterMotion(0.12, reduceMotion)}
                      className="rounded-xl border border-border bg-card px-3 py-3 shadow-lg shadow-black/5"
                    >
                      <div className="flex items-start gap-3 px-1 pb-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-conduut-50">
                          <Info className="h-4 w-4 text-conduut-500" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-[13px] font-medium text-muted-foreground">
                            Conduut prepared a run approval
                          </p>
                          <h2 className="mt-0.5 text-[15px] font-medium leading-snug text-foreground">
                            Safe preview passed. Run the real workflow now?
                          </h2>
                          <p className="mt-1 text-[13px] leading-snug text-muted-foreground">
                            The live website check, Gmail send, and Sheets write
                            will happen only after approval.
                          </p>
                        </div>
                      </div>

                      <div className="space-y-2">
                        {[
                          "Connections checked",
                          "Preview passed",
                          "No live run yet",
                        ].map((label, index) => (
                          <div
                            key={label}
                            className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2"
                          >
                            <span
                              className={cn(
                                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                                index < 2
                                  ? "bg-success-light text-success"
                                  : "bg-conduut-50 text-conduut-700"
                              )}
                            >
                              {index < 2 ? (
                                <Check className="h-3 w-3" />
                              ) : (
                                <Circle className="h-2.5 w-2.5 fill-current" />
                              )}
                            </span>
                            <span className="text-[13px] text-foreground">
                              {label}
                            </span>
                          </div>
                        ))}
                      </div>

                      <div className="mt-2 rounded-lg border border-border bg-background px-3 py-2">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-[12px] font-medium text-muted-foreground">
                              Reply
                            </p>
                            <p className="mt-0.5 text-[13px] text-foreground">
                              Approve or cancel this run.
                            </p>
                          </div>
                          <Badge
                            variant="outline"
                            className="px-2 py-0.5 text-[11px]"
                          >
                            Awaiting approval
                          </Badge>
                        </div>

                        <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                          <div className="flex min-h-11 items-center gap-2 rounded-lg border border-conduut-500 bg-conduut-50 px-3 text-left text-[14px] font-medium text-conduut-700">
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-conduut-500 text-white">
                              <Check className="h-3.5 w-3.5" />
                            </span>
                            <span className="min-w-0 flex-1">Approve run</span>
                          </div>
                          <div className="flex min-h-11 items-center gap-2 rounded-lg border border-border bg-background px-3 text-left text-[14px] font-medium text-foreground">
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                              2
                            </span>
                            <span className="min-w-0 flex-1">
                              Cancel for now
                            </span>
                          </div>
                        </div>

                        <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
                          <PencilLine className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="min-w-0 flex-1 text-[13px] text-muted-foreground">
                            Type a reply...
                          </span>
                          <span
                            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-conduut-500 text-white"
                            aria-hidden="true"
                          >
                            <SendHorizontal className="h-4 w-4" />
                          </span>
                        </div>
                      </div>
                    </motion.div>
                  ) : null}

                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
