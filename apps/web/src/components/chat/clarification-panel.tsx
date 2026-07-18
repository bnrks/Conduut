"use client";

import { FormEvent, useMemo, useState } from "react";
import { Check, HelpCircle, PencilLine, SendHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ClarificationChoice {
  label: string;
  value?: string;
}

export interface ClarificationStructuredResponse {
  request_id: string;
  request_kind: "workflow_run_approval";
  workflow_id: string;
  decision: "approve" | "cancel";
}

export interface ClarificationSubmitPayload {
  content: string;
  structuredResponse?: ClarificationStructuredResponse;
}

export interface ClarificationPanelData {
  question: string;
  missingFields?: string[];
  choices?: Array<ClarificationChoice | string>;
  reason?: string;
  requestId?: string;
  requestKind?: string;
  workflowId?: string;
}

export function ClarificationPanel({
  data,
  onSubmit,
  className,
}: {
  data: ClarificationPanelData;
  onSubmit: (payload: ClarificationSubmitPayload) => void;
  className?: string;
}) {
  const [customValue, setCustomValue] = useState("");
  const [selectedValue, setSelectedValue] = useState("");
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const choices = useMemo(
    () =>
      Array.isArray(data.choices)
        ? data.choices
            .map((choice) => (typeof choice === "string" ? { label: choice } : choice))
            .filter((choice) => choice.label)
        : [],
    [data.choices]
  );
  const missingFields = useMemo(
    () =>
      Array.isArray(data.missingFields)
        ? data.missingFields
            .map((field) => field.trim())
            .filter((field) => field.length > 0)
        : [],
    [data.missingFields]
  );
  const hasFieldInputs = missingFields.length > 1;
  const choiceField =
    hasFieldInputs && choices.length > 0 ? missingFields[0] : undefined;
  const textInputFields =
    hasFieldInputs && choiceField
      ? missingFields.filter((field) => field !== choiceField)
      : missingFields;
  const showStandaloneChoices = choices.length > 0 && !hasFieldInputs;
  const showCustomAnswer = choices.length === 0 && !hasFieldInputs;
  const showFieldForm = hasFieldInputs;
  const showMissingFieldSummary = missingFields.length > 0 && !hasFieldInputs;

  const canSubmitFields =
    hasFieldInputs &&
    missingFields.every((field) => fieldValues[field]?.trim().length > 0);

  const submit = (
    value: string,
    structuredResponse?: ClarificationStructuredResponse
  ) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit({ content: trimmed, structuredResponse });
    setCustomValue("");
    setSelectedValue("");
    setFieldValues({});
  };

  const buildStructuredResponse = (
    choice: ClarificationChoice
  ): ClarificationStructuredResponse | undefined => {
    if (
      data.requestKind !== "workflow_run_approval" ||
      !data.requestId ||
      !data.workflowId ||
      (choice.value !== "approve" && choice.value !== "cancel")
    ) {
      return undefined;
    }

    return {
      request_id: data.requestId,
      request_kind: "workflow_run_approval",
      workflow_id: data.workflowId,
      decision: choice.value,
    };
  };

  const submitCustom = (event: FormEvent) => {
    event.preventDefault();
    if (hasFieldInputs) {
      if (!canSubmitFields) return;
      submit(
        missingFields
          .map((field) => `${field}: ${fieldValues[field].trim()}`)
          .join("\n")
      );
      return;
    }
    if (missingFields.length === 1) {
      submit(`${missingFields[0]}: ${customValue}`);
      return;
    }
    submit(customValue);
  };

  const applyChoice = (choice: ClarificationChoice) => {
    const value = choice.value || choice.label;
    const structuredResponse = buildStructuredResponse(choice);
    const displayValue = structuredResponse ? choice.label : value;
    setSelectedValue(value);
    if (choiceField) {
      setFieldValues((current) => ({ ...current, [choiceField]: value }));
      return;
    }
    if (missingFields.length === 1) {
      submit(`${missingFields[0]}: ${displayValue}`, structuredResponse);
      return;
    }
    submit(displayValue, structuredResponse);
  };

  return (
    <section
      className={cn(
        "max-h-[min(58vh,420px)] overflow-y-auto rounded-xl border border-border bg-card shadow-lg shadow-black/10",
        "px-3 py-3",
        className
      )}
    >
      <div className="flex items-start gap-3 px-1 pb-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-conduut-50">
          <HelpCircle className="h-4 w-4 text-conduut-500" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-muted-foreground">
            {missingFields.length > 1
              ? `Conduut needs ${missingFields.length} details`
              : "Conduut needs one detail"}
          </p>
          <h2 className="mt-0.5 text-[15px] font-medium leading-snug text-foreground">
            {data.question}
          </h2>
          {data.reason && (
            <p className="mt-1 text-[13px] leading-snug text-muted-foreground">
              {data.reason}
            </p>
          )}
        </div>
      </div>

      {showMissingFieldSummary && (
        <div className="mb-2 rounded-lg border border-border bg-background px-3 py-2">
          <p className="text-[12px] font-medium text-muted-foreground">
            Gerekli bilgiler
          </p>
          <ul className="mt-1.5 grid gap-1 text-[13px] text-foreground sm:grid-cols-2">
            {missingFields.map((field) => (
              <li key={field} className="flex min-w-0 items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-conduut-500" />
                <span className="min-w-0 break-words">{field}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {showStandaloneChoices && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {choices.map((choice, index) => {
            const value = choice.value || choice.label;
            const selected = selectedValue === value;
            return (
              <button
                key={`${choice.label}-${index}`}
                type="button"
                onClick={() => {
                  applyChoice(choice);
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

      {(showFieldForm || showCustomAnswer) && (
        <form
          onSubmit={submitCustom}
          className={cn(
            "mt-2 rounded-lg border border-border bg-background",
            showFieldForm ? "px-3 py-3" : "flex items-center gap-2 px-3 py-2"
          )}
        >
          {showFieldForm ? (
            <div className="space-y-2">
              {choiceField && (
                <div>
                  <p className="text-[12px] font-medium text-muted-foreground">
                    {choiceField}
                  </p>
                  <div className="mt-1 grid gap-1.5 sm:grid-cols-2">
                    {choices.map((choice, index) => {
                      const value = choice.value || choice.label;
                      const selected = fieldValues[choiceField] === value;
                      return (
                        <button
                          key={`${choice.label}-${index}`}
                          type="button"
                          onClick={() => {
                            applyChoice(choice);
                          }}
                          className={cn(
                            "flex min-h-10 items-center gap-2 rounded-lg border px-3 text-left",
                            "text-[14px] font-medium transition-colors",
                            selected
                              ? "border-conduut-500 bg-conduut-50 text-conduut-700"
                              : "border-border bg-card text-foreground hover:border-conduut-200 hover:bg-conduut-50/60"
                          )}
                        >
                          <span
                            className={cn(
                              "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[12px] font-semibold",
                              selected
                                ? "bg-conduut-500 text-white"
                                : "bg-muted text-muted-foreground"
                            )}
                          >
                            {selected ? (
                              <Check className="h-3.5 w-3.5" />
                            ) : (
                              index + 1
                            )}
                          </span>
                          <span className="min-w-0 flex-1 break-words">
                            {choice.label}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {textInputFields.map((field) => (
                <label key={field} className="block">
                  <span className="text-[12px] font-medium text-muted-foreground">
                    {field}
                  </span>
                  <input
                    value={fieldValues[field] ?? ""}
                    onChange={(event) =>
                      setFieldValues((current) => ({
                        ...current,
                        [field]: event.target.value,
                      }))
                    }
                    placeholder={`${field} gir...`}
                    className="mt-1 h-10 w-full rounded-md border border-border bg-card px-3 text-[14px] text-foreground placeholder:text-muted-foreground focus:border-conduut-300 focus:outline-none focus:ring-2 focus:ring-conduut-100"
                  />
                </label>
              ))}
              <div className="flex justify-end pt-1">
                <button
                  type="submit"
                  disabled={!canSubmitFields}
                  className={cn(
                    "inline-flex h-9 items-center gap-2 rounded-full px-3 text-[13px] font-medium",
                    "bg-conduut-500 text-white transition-colors hover:bg-conduut-700",
                    "disabled:cursor-not-allowed disabled:opacity-40"
                  )}
                >
                  <span>Bilgileri gönder</span>
                  <SendHorizontal className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : (
            <>
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
            </>
          )}
        </form>
      )}
    </section>
  );
}
