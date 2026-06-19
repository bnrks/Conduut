"use client";

import { FormEvent, useMemo, useState } from "react";
import { KeyRound, CheckCircle, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

export interface CredentialField {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
}

export interface CredentialTypeOption {
  type: string;
  label: string;
  fields: CredentialField[];
}

export interface CredentialRequestData {
  workflowId: string;
  workflowName?: string;
  nodeName: string;
  service: string;
  credentialType: string;
  credentialName: string;
  fields: CredentialField[];
  submitPath: string;
  description: string;
  allowedTypes?: CredentialTypeOption[];
  host?: string;
}

const CUSTOM_JSON_PLACEHOLDER = '{"headers": {"X-API-Key": "your-key"}}';

export function CredentialRequest({
  data,
  className,
}: {
  data: CredentialRequestData;
  className?: string;
}) {
  const { user } = useAuth();

  // When the backend offers a type picker (generic HTTP auth), the user chooses
  // which scheme; otherwise we use the single credentialType from the request.
  const typeOptions = useMemo<CredentialTypeOption[]>(() => {
    if (data.allowedTypes && data.allowedTypes.length > 0) return data.allowedTypes;
    return [
      {
        type: data.credentialType,
        label: data.service || data.credentialType,
        fields:
          data.fields.length > 0
            ? data.fields
            : [{ name: "apiKey", label: "API Key", type: "password", required: true }],
      },
    ];
  }, [data.allowedTypes, data.credentialType, data.fields, data.service]);

  const hasHost = data.host !== undefined && data.host !== null;

  const [selectedType, setSelectedType] = useState(typeOptions[0].type);
  const [values, setValues] = useState<Record<string, string>>({});
  const [host, setHost] = useState(data.host ?? "");
  const [label, setLabel] = useState(data.credentialName ?? "");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState("");

  const activeOption = useMemo(
    () => typeOptions.find((option) => option.type === selectedType) ?? typeOptions[0],
    [typeOptions, selectedType]
  );

  const isCustom = selectedType === "httpCustomAuth";
  const showTypePicker = typeOptions.length > 1;

  const buildData = (): Record<string, unknown> | null => {
    if (isCustom) {
      const fieldName = activeOption.fields[0]?.name ?? "json";
      const raw = values[fieldName] ?? "";
      try {
        JSON.parse(raw);
      } catch {
        setError("Auth JSON must be valid JSON.");
        return null;
      }
      return { [fieldName]: raw };
    }
    const payload: Record<string, string> = {};
    for (const field of activeOption.fields) {
      payload[field.name] = values[field.name] ?? "";
    }
    return payload;
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!user) return;
    setError("");

    if (hasHost && !host.trim()) {
      setError("Host is required (e.g. api.example.com).");
      return;
    }
    const credentialData = buildData();
    if (credentialData === null) return;

    setStatus("saving");
    try {
      const token = await user.getIdToken();
      const response = await fetch(data.submitPath, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          workflow_id: data.workflowId,
          node_name: data.nodeName,
          service: data.service,
          credential_type: selectedType,
          generic_auth_type: showTypePicker || hasHost ? selectedType : undefined,
          credential_name: label || data.credentialName,
          host: hasHost ? host.trim() : undefined,
          data: credentialData,
        }),
      });
      const payload = (await response.json().catch(() => null)) as {
        message?: string;
        detail?: { message?: string } | string;
      } | null;
      if (!response.ok) {
        const message =
          typeof payload?.detail === "string"
            ? payload.detail
            : payload?.detail?.message || payload?.message || "Credential could not be saved.";
        throw new Error(message);
      }
      setStatus("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Credential could not be saved.");
      setStatus("error");
    }
  };

  return (
    <form
      onSubmit={submit}
      className={cn("mt-2 w-full rounded-lg border border-border bg-card p-3", className)}
    >
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-conduut-50">
          <KeyRound className="h-4 w-4 text-conduut-500" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-medium text-foreground">Connect {data.service}</p>
          <p className="text-[12px] text-muted-foreground">{data.description}</p>
        </div>
        {status === "saved" && <CheckCircle className="h-5 w-5 text-success" />}
      </div>

      {status !== "saved" && (
        <div className="space-y-2">
          {showTypePicker && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                Authentication type
              </span>
              <select
                value={selectedType}
                onChange={(event) => {
                  setSelectedType(event.target.value);
                  setValues({});
                  setError("");
                }}
                className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-[13px] text-foreground transition-colors hover:border-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {typeOptions.map((option) => (
                  <option key={option.type} value={option.type}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
              Credential name
            </span>
            <Input
              type="text"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="e.g. Stripe API"
              className="h-9 text-[13px]"
            />
          </label>

          {hasHost && (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                Host
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

          {isCustom ? (
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                {activeOption.fields[0]?.label ?? "Auth JSON"}
              </span>
              <Textarea
                value={values[activeOption.fields[0]?.name ?? "json"] ?? ""}
                onChange={(event) =>
                  setValues((prev) => ({
                    ...prev,
                    [activeOption.fields[0]?.name ?? "json"]: event.target.value,
                  }))
                }
                placeholder={CUSTOM_JSON_PLACEHOLDER}
                className="min-h-[88px] font-mono text-[12px]"
              />
            </label>
          ) : (
            activeOption.fields.map((field) => (
              <label key={field.name} className="block">
                <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                  {field.label}
                </span>
                <Input
                  type={field.type === "password" ? "password" : "text"}
                  required={field.required}
                  value={values[field.name] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.name]: event.target.value }))
                  }
                  className="h-9 text-[13px]"
                />
              </label>
            ))
          )}

          {error && (
            <p className="flex items-center gap-1.5 text-[12px] text-error">
              <AlertCircle className="h-3.5 w-3.5" />
              {error}
            </p>
          )}
          <Button type="submit" size="sm" disabled={status === "saving"} className="w-full">
            {status === "saving" && <Spinner size="sm" className="text-white" />}
            Save credential
          </Button>
        </div>
      )}

      {status === "saved" && (
        <p className="text-[12px] text-muted-foreground">
          Credential saved and attached. Ask the agent to run the workflow again.
        </p>
      )}
    </form>
  );
}
