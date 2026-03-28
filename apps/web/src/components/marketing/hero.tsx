"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Sparkles } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const CHAT_MESSAGES = [
  {
    role: "user" as const,
    text: "When someone fills out my Typeform, add them to Google Sheets and send a Slack notification.",
  },
  {
    role: "agent" as const,
    text: "I'll build that workflow for you. Connecting Typeform → Google Sheets → Slack…",
  },
  {
    role: "agent" as const,
    text: "Workflow created and active. 3 steps, 0 code required.",
    isResult: true,
  },
];

const fadeUpProps = (delay: number) => ({
  initial: { opacity: 0, y: 24 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, delay, ease: "easeOut" as const },
});

export function Hero() {
  return (
    <section className="relative overflow-hidden bg-white pt-28 pb-20 sm:pt-36 sm:pb-28">
      {/* Background gradient */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-conduut-50/60 via-white to-white"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 w-[900px] h-[500px] rounded-full bg-conduut-100/30 blur-3xl"
      />

      <div className="relative mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 text-center">
        {/* Badge */}
        <motion.div
          {...fadeUpProps(0)}
          className="inline-flex items-center gap-2 rounded-full border border-conduut-200 bg-conduut-50 px-3.5 py-1 text-[13px] font-medium text-conduut-700 mb-6"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Powered by Claude AI
        </motion.div>

        {/* Headline */}
        <motion.h1
          {...fadeUpProps(0.08)}
          className="text-4xl sm:text-5xl md:text-6xl font-medium tracking-tight text-charcoal leading-[1.15]"
        >
          Build automations
          <br />
          <span className="text-conduut-500">by talking to AI.</span>
        </motion.h1>

        {/* Subtitle */}
        <motion.p
          {...fadeUpProps(0.16)}
          className="mt-6 max-w-2xl mx-auto text-[17px] sm:text-lg leading-relaxed text-gray-500"
        >
          Conduut turns plain English into live n8n workflows. Describe what you
          need, connect your apps, and your automation is running — no JSON,
          no&nbsp;OAuth pain, no code.
        </motion.p>

        {/* CTAs */}
        <motion.div
          {...fadeUpProps(0.24)}
          className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3"
        >
          <Link
            href="/register"
            className={cn(buttonVariants({ size: "lg" }))}
          >
            Start Free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <a
            href="#how-it-works"
            className={cn(buttonVariants({ variant: "outline", size: "lg" }))}
          >
            See how it works
          </a>
        </motion.div>

        <motion.p
          {...fadeUpProps(0.3)}
          className="mt-4 text-[13px] text-gray-400"
        >
          Free plan available — no credit card required
        </motion.p>

        {/* Chat mockup */}
        <motion.div
          {...fadeUpProps(0.38)}
          className="mt-14 mx-auto max-w-xl"
        >
          <div className="rounded-2xl border border-gray-200 bg-white shadow-xl shadow-gray-100 overflow-hidden">
            {/* Mockup header */}
            <div className="flex items-center gap-2 border-b border-gray-100 px-4 py-3 bg-gray-50">
              <div className="h-2.5 w-2.5 rounded-full bg-red-300" />
              <div className="h-2.5 w-2.5 rounded-full bg-yellow-300" />
              <div className="h-2.5 w-2.5 rounded-full bg-green-300" />
              <span className="ml-2 text-[12px] text-gray-400 font-mono">
                Conduut Chat
              </span>
            </div>

            {/* Messages */}
            <div className="p-5 flex flex-col gap-3">
              {CHAT_MESSAGES.map((msg, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.6 + i * 0.25, duration: 0.4 }}
                  className={
                    msg.role === "user"
                      ? "flex justify-end"
                      : "flex justify-start"
                  }
                >
                  {msg.role === "agent" && (
                    <div className="h-6 w-6 rounded-full bg-conduut-500 flex items-center justify-center mr-2 flex-shrink-0 mt-0.5">
                      <Sparkles className="h-3 w-3 text-white" />
                    </div>
                  )}
                  <div
                    className={`max-w-[80%] rounded-xl px-4 py-2.5 text-[14px] leading-relaxed ${
                      msg.role === "user"
                        ? "bg-conduut-500 text-white"
                        : msg.isResult
                          ? "bg-success-light text-success border border-success/20 font-medium"
                          : "bg-gray-100 text-charcoal"
                    }`}
                  >
                    {msg.text}
                  </div>
                </motion.div>
              ))}

              {/* Typing indicator */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 1.6, duration: 0.3 }}
                className="flex items-center gap-2 mt-1"
              >
                <div className="h-6 w-6 rounded-full bg-conduut-500 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="h-3 w-3 text-white" />
                </div>
                <div className="flex gap-1 items-center bg-gray-100 rounded-xl px-4 py-3">
                  {[0, 1, 2].map((dot) => (
                    <motion.div
                      key={dot}
                      className="h-1.5 w-1.5 rounded-full bg-gray-400"
                      animate={{ opacity: [0.3, 1, 0.3] }}
                      transition={{
                        repeat: Infinity,
                        duration: 1.2,
                        delay: dot * 0.2,
                      }}
                    />
                  ))}
                </div>
              </motion.div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
