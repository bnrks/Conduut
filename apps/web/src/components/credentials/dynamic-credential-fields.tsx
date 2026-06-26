"use client";

import { FormEvent, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";

export interface CredentialFieldOptionSpec {
  label: string;
  value: string;
}

export interface CredentialFieldSpec {
  name: string;
  label: string;
  type: string; // text | password | json | number | boolean | options
  required?: boolean;
  default?: unknown;
  placeholder?: string;
  description?: string;
  advanced?: boolean;
  options?: CredentialFieldOptionSpec[];
  showWhen?: { field: string; values: unknown[] };
}

export interface DynamicCredentialFieldsProps {
  fields: CredentialFieldSpec[];
  submitLabel?: string;
  onSubmit: (data: Record<string, unknown>) => Promise<void>;
}

function initialValues(fields: CredentialFieldSpec[]): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    values[field.name] = field.default ?? (field.type === "boolean" ? false : "");
  }
  return values;
}

function isVisible(field: CredentialFieldSpec, values: Record<string, unknown>): boolean {
  if (!field.showWhen) return true;
  const current = values[field.showWhen.field];
  return field.showWhen.values.some((value) => value === current);
}

export function DynamicCredentialFields({
  fields,
  submitLabel = "Save credential",
  onSubmit,
}: DynamicCredentialFieldsProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(fields));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const hasAdvanced = useMemo(() => fields.some((f) => f.advanced), [fields]);

  const setValue = (name: string, value: unknown) =>
    setValues((prev) => ({ ...prev, [name]: value }));

  const visible = fields.filter(
    (field) => isVisible(field, values) && (!field.advanced || showAdvanced)
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    for (const field of fields) {
      if (field.required && isVisible(field, values) && !String(values[field.name] ?? "").trim()) {
        setError(`${field.label} is required.`);
        return;
      }
    }
    // Only submit fields that are currently visible (respect conditional hiding).
    const data: Record<string, unknown> = {};
    for (const field of fields) {
      if (isVisible(field, values)) data[field.name] = values[field.name];
    }
    setSaving(true);
    try {
      await onSubmit(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Credential could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const renderControl = (field: CredentialFieldSpec) => {
    const value = values[field.name];
    if (field.type === "boolean") {
      return (
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => setValue(field.name, event.target.checked)}
            className="h-4 w-4 rounded border-input text-conduut-500 focus-visible:ring-2 focus-visible:ring-ring"
          />
          <span className="text-[12px] text-muted-foreground">{field.description ?? "Enable"}</span>
        </label>
      );
    }
    if (field.type === "options") {
      return (
        <select
          value={String(value ?? "")}
          onChange={(event) => setValue(field.name, event.target.value)}
          className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-[13px] text-foreground hover:border-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {(field.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      );
    }
    if (field.type === "json") {
      return (
        <Textarea
          value={String(value ?? "")}
          placeholder={field.placeholder}
          onChange={(event) => setValue(field.name, event.target.value)}
          className="min-h-[88px] font-mono text-[12px]"
        />
      );
    }
    return (
      <Input
        type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
        value={String(value ?? "")}
        placeholder={field.placeholder}
        onChange={(event) => setValue(field.name, event.target.value)}
        className="h-9 text-[13px]"
      />
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      {visible.map((field) => (
        <label key={field.name} className="block">
          <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
            {field.label}
            {field.required && <span className="ml-0.5 text-error">*</span>}
          </span>
          {renderControl(field)}
          {field.description && field.type !== "boolean" && (
            <span className="mt-1 block text-[11px] text-muted-foreground">{field.description}</span>
          )}
        </label>
      ))}

      {hasAdvanced && (
        <button
          type="button"
          onClick={() => setShowAdvanced((open) => !open)}
          className="text-[12px] font-medium text-conduut-500 hover:text-conduut-700"
        >
          {showAdvanced ? "Hide advanced options" : "Advanced options"}
        </button>
      )}

      {error && (
        <p className="flex items-center gap-1.5 text-[12px] text-error">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </p>
      )}

      <Button type="submit" size="sm" disabled={saving} className="w-full">
        {saving && <Spinner size="sm" className="text-white" />}
        {submitLabel}
      </Button>
    </form>
  );
}
