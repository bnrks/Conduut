"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Spinner } from "@/components/ui/spinner";

interface AuthGuardProps {
  children: React.ReactNode;
  mode: "protected" | "guest";
}

export function AuthGuard({ children, mode }: AuthGuardProps) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;

    if (mode === "protected" && !user) {
      router.replace("/login");
    }

    if (mode === "guest" && user) {
      router.replace("/dashboard");
    }
  }, [user, loading, mode, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  if (mode === "protected" && !user) return null;
  if (mode === "guest" && user) return null;

  return <>{children}</>;
}
