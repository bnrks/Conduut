"use client";

import { useMemo, useState } from "react";
import { KeyRound, CheckCircle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";
import {
  AuthMethod,
  AUTH_METHODS,
  methodForCredentialType,
} from "@/lib/credential-auth-methods";
import {
  CredentialForm,
  type CredentialSubmission,
} from "@/components/credentials/credential-form";

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
  draftId?: string;
  sourceUrl?: string;
}

// Map the request's offered n8n credential types to plain-language auth methods.
// Falls back to a synthetic method when the request carries raw fields only
// (non-HTTP credential requests keep working).
function methodsFromRequest(data: CredentialRequestData): AuthMethod[] {
  if (data.allowedTypes && data.allowedTypes.length > 0) {
    const seen = new Set<string>();
    const methods: AuthMethod[] = [];
    for (const option of data.allowedTypes) {
      const method = methodForCredentialType(option.type);
      if (!seen.has(method.id)) {
        seen.add(method.id);
        methods.push(method);
      }
    }
    return methods.length > 0 ? methods : AUTH_METHODS;
  }
  return [
    {
      id: data.credentialType || "credential",
      credentialType: data.credentialType,
      label: data.service || "Credential",
      fields: (data.fields.length > 0
        ? data.fields
        : [{ name: "apiKey", label: "API Key", type: "password", required: true }]
      ).map((field) => ({
        name: field.name,
        label: field.label,
        type: field.type === "password" ? ("password" as const) : ("text" as const),
      })),
      buildData: (values) =>
        Object.fromEntries(data.fields.map((field) => [field.name, values[field.name] ?? ""])),
    },
  ];
}

export function CredentialRequest({
  data,
  className,
}: {
  data: CredentialRequestData;
  className?: string;
}) {
  const { user } = useAuth();
  const [saved, setSaved] = useState(false);
  const methods = useMemo(() => methodsFromRequest(data), [data]);
  const hasHost = data.host !== undefined && data.host !== null;

  const handleSubmit = async (submission: CredentialSubmission) => {
    if (!user) throw new Error("Please sign in first.");
    const token = await user.getIdToken();
    const response = await fetch(data.submitPath, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        workflow_id: data.workflowId,
        node_name: data.nodeName,
        service: data.service,
        credential_type: submission.credential_type,
        generic_auth_type: submission.generic_auth_type,
        credential_name: submission.label,
        host: submission.host,
        data: submission.data,
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
    setSaved(true);
  };

  return (
    <div className={cn("mt-2 w-full rounded-lg border border-border bg-card p-3", className)}>
      <div className="mb-3 flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-conduut-50">
          <KeyRound className="h-4 w-4 text-conduut-500" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-medium text-foreground">Connect {data.service}</p>
          <p className="text-[12px] text-muted-foreground">{data.description}</p>
        </div>
        {saved && <CheckCircle className="h-5 w-5 text-success" />}
      </div>

      {saved ? (
        <p className="text-[12px] text-muted-foreground">
          Credential saved and attached. Ask the agent to run the workflow again.
        </p>
      ) : (
        <CredentialForm
          methods={methods}
          requireHost={hasHost}
          initialHost={data.host ?? ""}
          initialLabel={data.credentialName}
          onSubmit={handleSubmit}
        />
      )}
    </div>
  );
}
