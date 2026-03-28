"use client";

import { motion } from "framer-motion";
import { MessageSquare, Wand2, Plug } from "lucide-react";

const STEPS = [
  {
    number: "1",
    icon: MessageSquare,
    title: "Describe what you need",
    description:
      "Tell the AI what you want to automate in plain English. No technical knowledge needed — just describe the outcome.",
  },
  {
    number: "2",
    icon: Wand2,
    title: "AI builds your workflow",
    description:
      "Conduut's AI understands your intent, selects the right integrations, and generates a complete workflow — instantly.",
  },
  {
    number: "3",
    icon: Plug,
    title: "Connect and automate",
    description:
      "Authorize your services with one click. Your workflow goes live in your own isolated cloud environment.",
  },
];

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.15,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 32 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut" as const },
  },
};

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="bg-white py-20 sm:py-28"
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
            How it works
          </p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-charcoal">
            From idea to live automation
            <br />
            in three steps.
          </h2>
        </motion.div>

        {/* Steps */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="grid grid-cols-1 md:grid-cols-3 gap-8 relative"
        >
          {/* Connector line — desktop */}
          <div
            aria-hidden
            className="hidden md:block absolute top-10 left-[calc(16.67%+1.5rem)] right-[calc(16.67%+1.5rem)] h-px bg-gradient-to-r from-transparent via-conduut-200 to-transparent"
          />

          {STEPS.map((step) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.number}
                variants={itemVariants}
                className="flex flex-col items-center text-center"
              >
                {/* Number badge + icon */}
                <div className="relative mb-5">
                  <div className="h-20 w-20 rounded-2xl bg-conduut-50 flex items-center justify-center">
                    <Icon className="h-8 w-8 text-conduut-500" />
                  </div>
                  <span className="absolute -top-2 -right-2 h-6 w-6 rounded-full bg-conduut-500 text-white text-[12px] font-medium flex items-center justify-center">
                    {step.number}
                  </span>
                </div>

                <h3 className="text-[17px] font-medium text-charcoal mb-2">
                  {step.title}
                </h3>
                <p className="text-[15px] text-gray-500 leading-relaxed max-w-xs">
                  {step.description}
                </p>
              </motion.div>
            );
          })}
        </motion.div>
      </div>
    </section>
  );
}
