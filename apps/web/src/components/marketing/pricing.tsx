"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Check, Zap } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PLAN_DETAILS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { PlanTier } from "@/types/user";

const PLAN_FEATURES: Record<PlanTier, string[]> = {
  free: [
    "2 active workflows",
    "500 executions / month",
    "2 connected services",
    "Shared container",
    "Community support",
  ],
  starter: [
    "10 active workflows",
    "5,000 executions / month",
    "5 connected services",
    "Dedicated container",
    "Email support",
    "Workflow templates",
  ],
  pro: [
    "50 active workflows",
    "25,000 executions / month",
    "Unlimited connections",
    "Dedicated container (1 CPU / 512 MB)",
    "Priority support",
    "Workflow templates",
    "Advanced analytics",
  ],
  enterprise: [
    "Unlimited workflows",
    "Unlimited executions",
    "Unlimited connections",
    "Dedicated VPS",
    "SLA guarantee",
    "Custom integrations",
    "Dedicated onboarding",
  ],
};

const PLAN_ORDER: PlanTier[] = ["free", "starter", "pro", "enterprise"];

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.1 } },
};

const cardVariants = {
  hidden: { opacity: 0, y: 28 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut" as const },
  },
};

export function Pricing() {
  return (
    <section id="pricing" className="bg-white py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Section header */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5, ease: "easeOut" as const }}
          className="text-center mb-14"
        >
          <p className="text-[13px] font-medium uppercase tracking-widest text-conduut-500 mb-3">
            Pricing
          </p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-charcoal">
            Simple, transparent pricing.
          </h2>
          <p className="mt-4 text-[16px] text-gray-500">
            Start free, scale when you need to. No surprises.
          </p>
        </motion.div>

        {/* Plan cards */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 items-start"
        >
          {PLAN_ORDER.map((tier) => {
            const plan = PLAN_DETAILS[tier];
            const features = PLAN_FEATURES[tier];
            const isPopular = plan.popular === true;
            const isEnterprise = tier === "enterprise";
            const isFree = tier === "free";

            return (
              <motion.div
                key={tier}
                variants={cardVariants}
                className={cn(
                  "relative rounded-xl border bg-white p-6 flex flex-col",
                  isPopular
                    ? "border-conduut-500 shadow-lg shadow-conduut-100"
                    : "border-gray-200"
                )}
              >
                {/* Popular badge */}
                {isPopular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <Badge className="flex items-center gap-1 bg-conduut-500 text-white rounded-full px-3 py-0.5 text-[12px] font-medium">
                      <Zap className="h-3 w-3" />
                      Popular
                    </Badge>
                  </div>
                )}

                {/* Plan name */}
                <p className="text-[13px] font-medium uppercase tracking-wide text-gray-500 mb-3">
                  {plan.name}
                </p>

                {/* Price */}
                <div className="mb-5">
                  {isEnterprise ? (
                    <p className="text-3xl font-medium text-charcoal">Custom</p>
                  ) : (
                    <div className="flex items-baseline gap-1">
                      <span className="text-3xl font-medium text-charcoal">
                        ${plan.price}
                      </span>
                      <span className="text-[14px] text-gray-400">/ month</span>
                    </div>
                  )}
                </div>

                {/* CTA button */}
                {isEnterprise ? (
                  <Link
                    href="/contact"
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full mb-6")}
                  >
                    Contact Us
                  </Link>
                ) : isFree ? (
                  <Link
                    href="/register"
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full mb-6")}
                  >
                    Get Started
                  </Link>
                ) : (
                  <Link
                    href="/register"
                    className={cn(
                      buttonVariants({ size: "sm" }),
                      "w-full mb-6",
                      !isPopular && "bg-charcoal hover:bg-gray-700"
                    )}
                  >
                    Start Free
                  </Link>
                )}

                {/* Divider */}
                <div className="border-t border-gray-100 mb-5" />

                {/* Feature list */}
                <ul className="flex flex-col gap-2.5 flex-1">
                  {features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2.5">
                      <Check className="h-4 w-4 text-success flex-shrink-0 mt-0.5" />
                      <span className="text-[13px] text-gray-600 leading-snug">
                        {feature}
                      </span>
                    </li>
                  ))}
                </ul>
              </motion.div>
            );
          })}
        </motion.div>

        {/* Bottom note */}
        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ delay: 0.4, duration: 0.4 }}
          className="mt-8 text-center text-[13px] text-gray-400"
        >
          All plans include a free trial period. Cancel anytime.
        </motion.p>
      </div>
    </section>
  );
}
