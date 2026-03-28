import type { Metadata } from "next";
import { Logo } from "@/components/ui/logo";
import { AuthCard } from "@/components/auth/auth-card";
import { OAuthButtons } from "@/components/auth/oauth-buttons";
import { AuthDivider } from "@/components/auth/auth-divider";
import { RegisterForm } from "@/components/auth/register-form";

export const metadata: Metadata = {
  title: "Sign up",
};

export default function RegisterPage() {
  return (
    <AuthCard>
      <div className="flex flex-col items-center gap-2 text-center">
        <Logo variant="full" className="h-8 lg:hidden" />
        <h1 className="text-2xl font-medium text-foreground tracking-tight">
          Create your account
        </h1>
        <p className="text-sm text-muted-foreground">
          Start automating in minutes
        </p>
      </div>

      <OAuthButtons />
      <AuthDivider />
      <RegisterForm />
    </AuthCard>
  );
}
