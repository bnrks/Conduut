"use client";

import { FormEvent, useMemo, useState } from "react";
import { Check, HelpCircle, PencilLine, SendHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ClarificationChoice {
  label: string;
  value?: string;
}

export interface ClarificationPanelData {
  question: string;
  choices?: Array<ClarificationChoice | string>;
}

export function ClarificationPanel({
  data,
  onSubmit,
  className,
}: {
  data: ClarificationPanelData;
  onSubmit: (value: string) => void;
  className?: string;
}) {
  const [customValue, setCustomValue] = useState("");
  const [selectedValue, setSelectedValue] = useState("");
  const choices = useMemo(
    () =>
      Array.isArray(data.choices)
        ? data.choices
            .map((choice) => (typeof choice === "string" ? { label: choice } : choice))
            .filter((choice) => choice.label)
        : [],
    [data.choices]
  );

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
    setCustomValue("");
    setSelectedValue("");
  };

  const submitCustom = (event: FormEvent) => {
    event.preventDefault();
    submit(customValue);
  };

  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-card shadow-lg shadow-black/5",
        "px-3 py-3",
        className
      )}
    >
      <div className="flex items-start gap-3 px-1 pb-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-conduut-50">
          <HelpCircle className="h-4 w-4 text-conduut-500" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-muted-foreground">Conduut needs one detail</p>
          <h2 className="mt-0.5 text-[16px] font-semibold leading-snug text-foreground">
            {data.question}
          </h2>
        </div>
      </div>

      {choices.length > 0 && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {choices.map((choice, index) => {
            const value = choice.value || choice.label;
            const selected = selectedValue === value;
            return (
              <button
                key={`${choice.label}-${index}`}
                type="button"
                onClick={() => {
                  setSelectedValue(value);
                  submit(value);
                }}
                className={cn(
                  "flex min-h-11 items-center gap-2 rounded-lg border px-3 text-left",
                  "text-[14px] font-medium transition-colors",
                  selected
                    ? "border-conduut-500 bg-conduut-50 text-conduut-700"
                    : "border-border bg-background text-foreground hover:border-conduut-200 hover:bg-conduut-50/60"
                )}
              >
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[12px] font-semibold",
                    selected ? "bg-conduut-500 text-white" : "bg-muted text-muted-foreground"
                  )}
                >
                  {selected ? <Check className="h-3.5 w-3.5" /> : index + 1}
                </span>
                <span className="min-w-0 flex-1 break-words">{choice.label}</span>
              </button>
            );
          })}
        </div>
      )}

      <form onSubmit={submitCustom} className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
        <PencilLine className="h-4 w-4 shrink-0 text-muted-foreground" />
        <input
          value={customValue}
          onChange={(event) => setCustomValue(event.target.value)}
          placeholder="Cevabını yaz..."
          className="min-w-0 flex-1 bg-transparent text-[14px] text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
        <button
          type="submit"
          disabled={!customValue.trim()}
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
            "bg-conduut-500 text-white transition-colors hover:bg-conduut-700",
            "disabled:cursor-not-allowed disabled:opacity-40"
          )}
          aria-label="Send answer"
        >
          <SendHorizontal className="h-4 w-4" />
        </button>
      </form>
    </section>
  );
}
