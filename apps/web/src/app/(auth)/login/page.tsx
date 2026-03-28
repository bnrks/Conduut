import type { Metadata } from "next";
import { Logo } from "@/components/ui/logo";
import { AuthCard } from "@/components/auth/auth-card";
import { OAuthButtons } from "@/components/auth/oauth-buttons";
import { AuthDivider } from "@/components/auth/auth-divider";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Log in",
};

export default function LoginPage() {
  return (
    <AuthCard>
      <div className="flex flex-col items-center gap-2 text-center">
        <Logo variant="full" className="h-8 lg:hidden" />
        <h1 className="text-2xl font-medium text-foreground tracking-tight">
          Welcome back
        </h1>
        <p className="text-sm text-muted-foreground">Sign in to your account</p>
      </div>

      <OAuthButtons />
      <AuthDivider />
      <LoginForm />
    </AuthCard>
  );
}
