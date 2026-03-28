"use client";

import { motion } from "framer-motion";
import {
  MessageSquare,
  Shield,
  Lock,
  Puzzle,
  Play,
  BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";

const FEATURES = [
  {
    icon: MessageSquare,
    title: "Natural Language",
    description:
      "Describe workflows in plain English. No JSON schemas, no node editors — just say what you want to automate.",
  },
  {
    icon: Shield,
    title: "OAuth Made Simple",
    description:
      "Connect Google, Slack, Notion and more with one click. We handle token storage, refresh, and revocation.",
  },
  {
    icon: Lock,
    title: "Isolated & Secure",
    description:
      "Each user gets their own n8n container with CPU, memory, and network isolation. Your data never touches another tenant.",
  },
  {
    icon: Puzzle,
    title: "400+ Integrations",
    description:
      "Google Workspace, Slack, Notion, GitHub, Discord, Airtable, Telegram — and hundreds more through n8n's ecosystem.",
  },
  {
    icon: Play,
    title: "Real-time Testing",
    description:
      "Test workflows instantly after creation. See execution logs and fix issues through conversation, not config panels.",
  },
  {
    icon: BarChart3,
    title: "Usage Dashboard",
    description:
      "Monitor execution counts, active workflows, and connected services. Know exactly what's running and when.",
  },
];

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.08,
    },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, ease: "easeOut" as const },
  },
};

export function Features() {
  return (
    <section
      id="features"
      className="bg-gray-50 py-20 sm:py-28"
    >
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5, ease: "easeOut" as const }}
          className="text-center mb-14"
        >
          <p className="text-[13px] font-medium uppercase tracking-widest text-conduut-500 mb-3">
            Features
          </p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-charcoal">
            Everything you need to automate.
          </h2>
          <p className="mt-4 text-[16px] text-gray-500 max-w-xl mx-auto leading-relaxed">
            A complete platform — from workflow generation to OAuth management
            — so you can focus on outcomes, not infrastructure.
          </p>
        </motion.div>

        {/* Feature grid */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {FEATURES.map((feature) => {
            const Icon = feature.icon;
            return (
              <motion.div
                key={feature.title}
                variants={cardVariants}
                className={cn(
                  "group rounded-xl border border-gray-200 bg-white p-6",
                  "transition-all duration-200",
                  "hover:shadow-md hover:bg-conduut-50 hover:border-conduut-200"
                )}
              >
                <div className="h-10 w-10 rounded-lg bg-conduut-50 group-hover:bg-white flex items-center justify-center mb-4 transition-colors duration-200">
                  <Icon className="h-5 w-5 text-conduut-500" />
                </div>
                <h3 className="text-[16px] font-medium text-charcoal mb-1.5">
                  {feature.title}
                </h3>
                <p className="text-[14px] text-gray-500 leading-relaxed">
                  {feature.description}
                </p>
              </motion.div>
            );
          })}
        </motion.div>
      </div>
    </section>
  );
}
