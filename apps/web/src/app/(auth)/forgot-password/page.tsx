import type { Metadata } from "next";
import { Logo } from "@/components/ui/logo";
import { AuthCard } from "@/components/auth/auth-card";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";

export const metadata: Metadata = {
  title: "Reset password",
};

export default function ForgotPasswordPage() {
  return (
    <AuthCard>
      <div className="flex flex-col items-center gap-2 text-center">
        <Logo variant="full" className="h-8 lg:hidden" />
        <h1 className="text-2xl font-medium text-foreground tracking-tight">
          Reset your password
        </h1>
      </div>

      <ForgotPasswordForm />
    </AuthCard>
  );
}
