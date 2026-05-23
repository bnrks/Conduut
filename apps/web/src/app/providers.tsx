"use client";

import { ConfirmDialogProvider } from "@/components/ui/confirm-dialog";

export function Providers({ children }: { children: React.ReactNode }) {
  return <ConfirmDialogProvider>{children}</ConfirmDialogProvider>;
}
