"use client";

import { FormEvent, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import {
  AuthMethod,
  AuthMethodField,
  defaultValues,
} from "@/lib/credential-auth-methods";

const CUSTOM_JSON_PLACEHOLDER = '{"headers": {"X-API-Key": "your-key"}}';

export interface CredentialSubmission {
  credential_type: string;
  generic_auth_type: string;
  label: string;
  host?: string;
  data: Record<string, unknown>;
}

export interface CredentialFormProps {
  methods: AuthMethod[];
  requireHost: boolean;
  initialHost?: string;
  initialLabel?: string;
  submitLabel?: string;
  // Draft finalize: hide the method picker, Name and host inputs — the agent
  // pre-configured everything and the user only enters the secret.
  secretOnly?: boolean;
  onSubmit: (submission: CredentialSubmission) => Promise<void>;
}

export function CredentialForm({
  methods,
  requireHost,
  initialHost,
  initialLabel,
  submitLabel = "Save credential",
  secretOnly = false,
  onSubmit,
}: CredentialFormProps) {
  const primaryMethods = useMemo(() => methods.filter((m) => !m.advanced), [methods]);
  const advancedMethods = useMemo(() => methods.filter((m) => m.advanced), [methods]);

  const [selectedId, setSelectedId] = useState((primaryMethods[0] ?? methods[0]).id);
  const method = useMemo(
    () => methods.find((m) => m.id === selectedId) ?? methods[0],
    [methods, selectedId]
  );

  const [values, setValues] = useState<Record<string, string>>(() => defaultValues(method));
  const [host, setHost] = useState(initialHost ?? "");
  const [label, setLabel] = useState(initialLabel ?? "");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const hasAdvanced =
    !secretOnly &&
    (advancedMethods.length > 0 || method.fields.some((field) => field.advanced));
  const showMethodPicker = !secretOnly && (primaryMethods.length > 1 || advancedMethods.length > 0);

  const selectMethod = (id: string) => {
    const next = methods.find((m) => m.id === id);
    if (!next) return;
    setSelectedId(id);
    setValues(defaultValues(next));
    setError("");
  };

  const visibleFields = method.fields.filter((field) => !field.advanced || showAdvanced);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (requireHost && !host.trim()) {
      setError("Host is required (e.g. api.example.com).");
      return;
    }
    const data = method.buildData(values);
    if (method.credentialType === "httpCustomAuth") {
      try {
        JSON.parse(String((data as { json?: string }).json ?? ""));
      } catch {
        setError("Auth JSON must be valid JSON.");
        return;
      }
    }

    setSaving(true);
    try {
      await onSubmit({
        credential_type: method.credentialType,
        generic_auth_type: method.credentialType,
        label: label.trim() || method.label,
        host: requireHost ? host.trim() : undefined,
        data,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Credential could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const renderField = (field: AuthMethodField) => {
    if (field.type === "json") {
      return (
        <Textarea
          value={values[field.name] ?? ""}
          onChange={(event) =>
            setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
          }
          placeholder={CUSTOM_JSON_PLACEHOLDER}
          className="min-h-[88px] font-mono text-[12px]"
        />
      );
    }
    return (
      <Input
        type={field.type === "password" ? "password" : "text"}
        value={values[field.name] ?? ""}
        placeholder={field.placeholder}
        onChange={(event) =>
          setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
        }
        className="h-9 text-[13px]"
      />
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      {showMethodPicker && (
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
            How do you connect to this service?
          </span>
          <select
            value={selectedId}
            onChange={(event) => selectMethod(event.target.value)}
            className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-[13px] text-foreground transition-colors hover:border-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {primaryMethods.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
            {showAdvanced &&
              advancedMethods.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
          </select>
          {method.description && (
            <span className="mt-1 block text-[11px] text-muted-foreground">
              {method.description}
            </span>
          )}
        </label>
      )}

      {!secretOnly && (
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
            Name
          </span>
          <Input
            type="text"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="e.g. Stripe API"
            className="h-9 text-[13px]"
          />
        </label>
      )}

      {!secretOnly && requireHost && (
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
            Service address
          </span>
          <Input
            type="text"
            required
            value={host}
            onChange={(event) => setHost(event.target.value)}
            placeholder="api.example.com"
            className="h-9 text-[13px]"
          />
        </label>
      )}

      {visibleFields.map((field) => (
        <label key={field.name} className="block">
          <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
            {field.label}
          </span>
          {renderField(field)}
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
