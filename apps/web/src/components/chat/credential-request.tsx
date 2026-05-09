"use client";

import { FormEvent, useMemo, useState } from "react";
import { KeyRound, CheckCircle, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

export interface CredentialField {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
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
}

export function CredentialRequest({
  data,
  className,
}: {
  data: CredentialRequestData;
  className?: string;
}) {
  const { user } = useAuth();
  const [values, setValues] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState("");

  const fields = useMemo(() => data.fields.length > 0 ? data.fields : [
    { name: "apiKey", label: "API Key", type: "password", required: true },
  ], [data.fields]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!user) return;
    setStatus("saving");
    setError("");
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
          credential_type: data.credentialType,
          credential_name: data.credentialName,
          data: values,
        }),
      });
      const payload = await response.json().catch(() => null) as { message?: string; detail?: { message?: string } | string } | null;
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
          <p className="text-[14px] font-medium text-foreground">
            Connect {data.service}
          </p>
          <p className="text-[12px] text-muted-foreground">{data.description}</p>
        </div>
        {status === "saved" && <CheckCircle className="h-5 w-5 text-success" />}
      </div>

      {status !== "saved" && (
        <div className="space-y-2">
          {fields.map((field) => (
            <label key={field.name} className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                {field.label}
              </span>
              <Input
                type={field.type === "password" ? "password" : "text"}
                required={field.required}
                value={values[field.name] ?? ""}
                onChange={(event) => setValues((prev) => ({ ...prev, [field.name]: event.target.value }))}
                className="h-9 text-[13px]"
              />
            </label>
          ))}
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
