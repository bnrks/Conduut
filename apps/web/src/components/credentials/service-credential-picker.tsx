"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import {
  serviceMethodFromFields,
  type ServiceCredentialField,
} from "@/lib/credential-auth-methods";
import {
  CredentialForm,
  type CredentialSubmission,
} from "@/components/credentials/credential-form";

interface CatalogEntry {
  type: string;
  label: string;
}

export interface ServiceCredentialPickerProps {
  onSubmit: (credentialType: string, label: string, data: Record<string, unknown>) => Promise<void>;
}

export function ServiceCredentialPicker({ onSubmit }: ServiceCredentialPickerProps) {
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [selected, setSelected] = useState<CatalogEntry | null>(null);
  const [fields, setFields] = useState<ServiceCredentialField[]>([]);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user || selected) return;
    let active = true;
    const handle = setTimeout(async () => {
      setLoadingList(true);
      try {
        const token = await user.getIdToken();
        const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
        const response = await fetch(`/api/credentials/catalog${suffix}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = (await response.json().catch(() => null)) as { catalog?: CatalogEntry[] } | null;
        if (active) setEntries(data?.catalog ?? []);
      } finally {
        if (active) setLoadingList(false);
      }
    }, 200);
    return () => {
      active = false;
      clearTimeout(handle);
    };
  }, [user, query, selected]);

  const pick = async (entry: CatalogEntry) => {
    if (!user) return;
    setSelected(entry);
    setError("");
    setLoadingSchema(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/credentials/catalog/${encodeURIComponent(entry.type)}/schema`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const data = (await response.json().catch(() => null)) as {
        fields?: ServiceCredentialField[];
        message?: string;
        detail?: { message?: string };
      } | null;
      if (!response.ok) {
        throw new Error(data?.detail?.message || data?.message || "Could not load fields.");
      }
      setFields(data?.fields ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load fields.");
      setSelected(null);
    } finally {
      setLoadingSchema(false);
    }
  };

  if (selected) {
    const method = serviceMethodFromFields(selected.type, selected.label, fields);
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => setSelected(null)}
          className="text-[12px] font-medium text-conduut-500 hover:text-conduut-700"
        >
          ← Choose a different service
        </button>
        <p className="text-[13px] font-medium text-foreground">{selected.label}</p>
        {loadingSchema ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : (
          <CredentialForm
            methods={[method]}
            requireHost={false}
            initialLabel={selected.label}
            submitLabel="Save credential"
            onSubmit={(submission: CredentialSubmission) =>
              onSubmit(selected.type, submission.label, submission.data)
            }
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search a service (OpenAI, Slack, Notion...)"
          className="h-9 pl-9 text-[13px]"
        />
      </div>
      {error && <p className="text-[12px] text-error">{error}</p>}
      <div className="max-h-64 space-y-1 overflow-y-auto">
        {loadingList ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : entries.length === 0 ? (
          <p className="px-1 py-4 text-center text-[12px] text-muted-foreground">
            No matching services.
          </p>
        ) : (
          entries.map((entry) => (
            <button
              key={entry.type}
              type="button"
              onClick={() => void pick(entry)}
              className="flex w-full items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-left text-[13px] text-foreground transition-colors hover:border-conduut-400"
            >
              <span>{entry.label}</span>
              <span className="text-[11px] text-muted-foreground">{entry.type}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
