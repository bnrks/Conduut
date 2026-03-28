export type PlanTier = "free" | "starter" | "pro" | "enterprise";

export interface User {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string;
  planTier: PlanTier;
  createdAt: string;
}

export interface Subscription {
  id: string;
  planTier: PlanTier;
  maxWorkflows: number;
  maxExecutionsMonthly: number;
  priceMonthly: number;
  status: "active" | "canceled" | "past_due";
  currentPeriodEnd: string;
}
