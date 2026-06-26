"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import {
  DynamicCredentialFields,
  type CredentialFieldSpec,
} from "@/components/credentials/dynamic-credential-fields";

interface CatalogEntry {
  type: string;
  label: string;
  icon_url?: string;
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
  const [fields, setFields] = useState<CredentialFieldSpec[]>([]);
  const [iconUrl, setIconUrl] = useState("");
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user || selected) return;
    let active = true;
    setLoadingList(true);
    const handle = setTimeout(async () => {
      try {
        const token = await user.getIdToken();
        const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
        const response = await fetch(`/api/credentials/catalog${suffix}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = (await response.json().catch(() => null)) as {
          catalog?: CatalogEntry[];
          message?: string;
          detail?: { message?: string };
        } | null;
        if (!response.ok) {
          throw new Error(data?.detail?.message ?? data?.message ?? "Could not load services.");
        }
        if (active) {
          setEntries(data?.catalog ?? []);
          setError("");
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load services.");
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
        fields?: CredentialFieldSpec[];
        label?: string;
        iconUrl?: string;
        message?: string;
        detail?: { message?: string };
      } | null;
      if (!response.ok) {
        throw new Error(data?.detail?.message || data?.message || "Could not load fields.");
      }
      setFields(data?.fields ?? []);
      setIconUrl(data?.iconUrl ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load fields.");
      setSelected(null);
    } finally {
      setLoadingSchema(false);
    }
  };

  if (selected) {
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => { setSelected(null); setError(""); setIconUrl(""); }}
          className="text-[12px] font-medium text-conduut-500 hover:text-conduut-700"
        >
          ← Choose a different service
        </button>
        <div className="flex items-center gap-2">
          {iconUrl && (
            <img
              src={`/api/credentials/icon?path=${encodeURIComponent(iconUrl)}`}
              className="h-4 w-4"
              alt=""
              onError={(event) => {
                (event.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
          )}
          <p className="text-[13px] font-medium text-foreground">{selected.label}</p>
        </div>
        {loadingSchema ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : (
          <DynamicCredentialFields
            fields={fields}
            submitLabel="Save credential"
            onSubmit={(data) => onSubmit(selected.type, selected.label, data)}
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
              <span className="flex items-center gap-2">
                {entry.icon_url && (
                  <img
                    src={`/api/credentials/icon?path=${encodeURIComponent(entry.icon_url)}`}
                    className="h-4 w-4"
                    alt=""
                    onError={(event) => {
                      (event.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                )}
                {entry.label}
              </span>
              <span className="text-[11px] text-muted-foreground">{entry.type}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
