"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function CtaSection() {
  return (
    <section className="relative overflow-hidden bg-charcoal py-20 sm:py-28">
      {/* Subtle accent glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center justify-center"
      >
        <div className="h-[500px] w-[700px] rounded-full bg-conduut-900/60 blur-3xl" />
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute top-0 left-1/4 h-px w-1/2 bg-gradient-to-r from-transparent via-conduut-700/50 to-transparent"
      />

      <div className="relative mx-auto max-w-3xl px-4 sm:px-6 lg:px-8 text-center">
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, ease: "easeOut" as const }}
          className="text-[13px] font-medium uppercase tracking-widest text-conduut-400 mb-4"
        >
          Get started today
        </motion.p>

        <motion.h2
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.08, ease: "easeOut" as const }}
          className="text-3xl sm:text-4xl md:text-5xl font-medium tracking-tight text-white leading-[1.2]"
        >
          Ready to automate
          <br />
          your work?
        </motion.h2>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.16, ease: "easeOut" as const }}
          className="mt-5 text-[16px] text-gray-400 leading-relaxed max-w-xl mx-auto"
        >
          Join teams that replaced hours of manual work with one conversation.
          Start free — no credit card, no setup headaches.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.24, ease: "easeOut" as const }}
          className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3"
        >
          <Link
            href="/register"
            className={cn(
              buttonVariants({ size: "lg" }),
              "bg-conduut-500 hover:bg-conduut-700 text-white"
            )}
          >
            Start Free
            <ArrowRight className="h-4 w-4" />
          </Link>
          <a
            href="#pricing"
            className={cn(
              buttonVariants({ variant: "ghost", size: "lg" }),
              "text-gray-400 hover:text-white hover:bg-white/10"
            )}
          >
            View pricing
          </a>
        </motion.div>
      </div>
    </section>
  );
}
