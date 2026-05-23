"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AlertTriangle, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ConfirmTone = "default" | "danger";

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
}

type ConfirmRequest = Required<ConfirmOptions>;
type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmDialogContext = createContext<ConfirmFn | null>(null);

export function ConfirmDialogProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const [settling, setSettling] = useState(false);
  const resolverRef = useRef<((confirmed: boolean) => void) | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);

  const resolveRequest = useCallback(
    (confirmed: boolean) => {
      if (!request || settling) return;
      setSettling(true);
      resolverRef.current?.(confirmed);
      resolverRef.current = null;
      setRequest(null);
      setSettling(false);
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    },
    [request, settling]
  );

  const confirm = useCallback<ConfirmFn>((options) => {
    resolverRef.current?.(false);
    setSettling(false);
    setRequest({
      title: options.title,
      description: options.description ?? "",
      confirmLabel: options.confirmLabel ?? "Confirm",
      cancelLabel: options.cancelLabel ?? "Cancel",
      tone: options.tone ?? "default",
    });

    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
    });
  }, []);

  useEffect(() => {
    if (!request) return;

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const frame = window.requestAnimationFrame(() => {
      cancelButtonRef.current?.focus();
    });

    return () => window.cancelAnimationFrame(frame);
  }, [request]);

  useEffect(() => {
    if (!request) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        resolveRequest(false);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [request, resolveRequest]);

  useEffect(() => {
    return () => {
      resolverRef.current?.(false);
    };
  }, []);

  const value = useMemo(() => confirm, [confirm]);
  const Icon = request?.tone === "danger" ? AlertTriangle : Info;

  return (
    <ConfirmDialogContext.Provider value={value}>
      {children}
      {request && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
          aria-describedby={
            request.description ? "confirm-dialog-description" : undefined
          }
          onClick={() => resolveRequest(false)}
        >
          <div
            className="w-full max-w-md rounded-lg border border-border bg-card p-5 text-card-foreground shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                  request.tone === "danger"
                    ? "bg-error-light text-error"
                    : "bg-muted text-muted-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h2
                  id="confirm-dialog-title"
                  className="text-[16px] font-medium leading-6 text-foreground"
                >
                  {request.title}
                </h2>
                {request.description && (
                  <p
                    id="confirm-dialog-description"
                    className="mt-1 text-[14px] leading-6 text-muted-foreground"
                  >
                    {request.description}
                  </p>
                )}
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button
                ref={cancelButtonRef}
                type="button"
                variant="outline"
                disabled={settling}
                onClick={() => resolveRequest(false)}
              >
                {request.cancelLabel}
              </Button>
              <Button
                type="button"
                variant={request.tone === "danger" ? "destructive" : "default"}
                disabled={settling}
                onClick={() => resolveRequest(true)}
              >
                {request.confirmLabel}
              </Button>
            </div>
          </div>
        </div>
      )}
    </ConfirmDialogContext.Provider>
  );
}

export function useConfirm() {
  const context = useContext(ConfirmDialogContext);
  if (!context) {
    throw new Error("useConfirm must be used within ConfirmDialogProvider.");
  }
  return context;
}
