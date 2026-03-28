import type { PlanTier } from "@/types/user";

export const PLAN_DETAILS: Record<
  PlanTier,
  {
    name: string;
    price: number;
    workflows: number;
    executionsMonthly: number;
    connections: number | "unlimited";
    popular?: boolean;
  }
> = {
  free: {
    name: "Free",
    price: 0,
    workflows: 2,
    executionsMonthly: 500,
    connections: 2,
  },
  starter: {
    name: "Starter",
    price: 15,
    workflows: 10,
    executionsMonthly: 5000,
    connections: 5,
    popular: true,
  },
  pro: {
    name: "Pro",
    price: 39,
    workflows: 50,
    executionsMonthly: 25000,
    connections: "unlimited",
  },
  enterprise: {
    name: "Enterprise",
    price: -1,
    workflows: Infinity,
    executionsMonthly: Infinity,
    connections: "unlimited",
  },
};
