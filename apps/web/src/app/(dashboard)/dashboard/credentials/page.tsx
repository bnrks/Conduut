"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";

interface CredentialField {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
}

interface CredentialTypeOption {
  type: string;
  label: string;
  description: string;
  hostRequired: boolean;
  fields: CredentialField[];
}

interface SavedCredential {
  id: string;
  label: string;
  credential_type: string;
  host: string;
  created_at?: string;
}

const CUSTOM_JSON_PLACEHOLDER = '{"headers": {"X-API-Key": "your-key"}}';

async function getErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as {
    detail?: { message?: string } | string;
    message?: string;
  } | null;
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.detail?.message === "string") return payload.detail.message;
  if (typeof payload?.message === "string") return payload.message;
  return fallback;
}

export default function CredentialsPage() {
  const { user, loading: authLoading } = useAuth();
  const confirm = useConfirm();
  const [credentials, setCredentials] = useState<SavedCredential[]>([]);
  const [types, setTypes] = useState<CredentialTypeOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [selectedType, setSelectedType] = useState("");
  const [label, setLabel] = useState("");
  const [host, setHost] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const activeType = useMemo(
    () => types.find((t) => t.type === selectedType) ?? types[0],
    [types, selectedType]
  );
  const isCustom = selectedType === "httpCustomAuth";

  const load = useCallback(async () => {
    if (!user) {
      setCredentials([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const token = await user.getIdToken();
      const headers = { Authorization: `Bearer ${token}` };
      const [listRes, typesRes] = await Promise.all([
        fetch("/api/credentials", { headers }),
        fetch("/api/credentials/types", { headers }),
      ]);
      if (!listRes.ok) throw new Error(await getErrorMessage(listRes, "Could not load credentials."));
      if (!typesRes.ok) throw new Error(await getErrorMessage(typesRes, "Could not load types."));
      const listData = (await listRes.json()) as { credentials?: SavedCredential[] };
      const typesData = (await typesRes.json()) as { types?: CredentialTypeOption[] };
      setCredentials(listData.credentials ?? []);
      setTypes(typesData.types ?? []);
      if (typesData.types && typesData.types.length > 0) {
        setSelectedType((current) => current || typesData.types![0].type);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not load credentials.");
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (authLoading) return;
    void load();
  }, [authLoading, load]);

  const resetForm = () => {
    setLabel("");
    setHost("");
    setValues({});
    setFormError("");
    if (types.length > 0) setSelectedType(types[0].type);
  };

  const buildData = (): Record<string, unknown> | null => {
    if (!activeType) return null;
    if (isCustom) {
      const fieldName = activeType.fields[0]?.name ?? "json";
      const raw = values[fieldName] ?? "";
      try {
        JSON.parse(raw);
      } catch {
        setFormError("Auth JSON must be valid JSON.");
        return null;
      }
      return { [fieldName]: raw };
    }
    const payload: Record<string, string> = {};
    for (const field of activeType.fields) {
      payload[field.name] = values[field.name] ?? "";
    }
    return payload;
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!user || !activeType) return;
    setFormError("");
    if (!host.trim()) {
      setFormError("Host is required (e.g. api.example.com).");
      return;
    }
    const data = buildData();
    if (data === null) return;

    setSaving(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch("/api/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          credential_type: selectedType,
          generic_auth_type: selectedType,
          label: label || activeType.label,
          host: host.trim(),
          data,
        }),
      });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Credential could not be saved."));
      }
      toast.success("Credential saved.");
      resetForm();
      setShowForm(false);
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Credential could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (credential: SavedCredential) => {
    if (!user) return;
    const confirmed = await confirm({
      title: "Delete credential?",
      description: `Conduut will delete "${credential.label}" and remove it from n8n.`,
      confirmLabel: "Delete",
      cancelLabel: "Cancel",
      tone: "danger",
    });
    if (!confirmed) return;

    setBusyId(credential.id);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/credentials/${encodeURIComponent(credential.id)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Credential could not be removed."));
      }
      setCredentials((prev) => prev.filter((item) => item.id !== credential.id));
      toast.success(`${credential.label} deleted.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Credential could not be removed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-medium text-foreground">Credentials</h1>
        <Button
          size="sm"
          onClick={() => {
            resetForm();
            setShowForm((open) => !open);
          }}
        >
          <Plus className="h-4 w-4" />
          Add credential
        </Button>
      </div>

      <p className="mb-4 max-w-2xl text-[13px] text-muted-foreground">
        Save reusable API credentials (header, basic, query, or custom auth). When Conduut
        builds a workflow that calls an API, it matches a saved credential by host and asks
        you to confirm before attaching it. Secrets are stored only in your n8n instance.
      </p>

      {showForm && (
        <Card className="mb-6">
          <CardContent className="p-4">
            <form onSubmit={submit} className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                  Authentication type
                </span>
                <select
                  value={selectedType}
                  onChange={(event) => {
                    setSelectedType(event.target.value);
                    setValues({});
                    setFormError("");
                  }}
                  className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-[13px] text-foreground transition-colors hover:border-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {types.map((option) => (
                    <option key={option.type} value={option.type}>
                      {option.label}
                    </option>
                  ))}
                </select>
                {activeType && (
                  <span className="mt-1 block text-[11px] text-muted-foreground">
                    {activeType.description}
                  </span>
                )}
              </label>

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

              {isCustom ? (
                <label className="block">
                  <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                    {activeType?.fields[0]?.label ?? "Auth JSON"}
                  </span>
                  <Textarea
                    value={values[activeType?.fields[0]?.name ?? "json"] ?? ""}
                    onChange={(event) =>
                      setValues((prev) => ({
                        ...prev,
                        [activeType?.fields[0]?.name ?? "json"]: event.target.value,
                      }))
                    }
                    placeholder={CUSTOM_JSON_PLACEHOLDER}
                    className="min-h-[88px] font-mono text-[12px]"
                  />
                </label>
              ) : (
                activeType?.fields.map((field) => (
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

              {formError && <p className="text-[12px] text-error">{formError}</p>}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowForm(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={saving}>
                  {saving && <Spinner size="sm" className="text-white" />}
                  Save credential
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : credentials.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 p-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-conduut-50">
              <KeyRound className="h-5 w-5 text-conduut-500" />
            </div>
            <p className="text-[14px] font-medium text-foreground">No credentials yet</p>
            <p className="text-[12px] text-muted-foreground">
              Add an API credential so Conduut can authenticate your HTTP workflows.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {credentials.map((credential) => (
            <Card key={credential.id}>
              <CardContent className="flex items-center gap-3 p-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-white">
                  <KeyRound className="h-4 w-4 text-conduut-500" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-[14px] font-medium text-foreground">
                      {credential.label}
                    </p>
                    <Badge variant="default" className="text-[11px]">
                      {credential.credential_type}
                    </Badge>
                  </div>
                  <p className="truncate text-[12px] text-muted-foreground">{credential.host}</p>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 shrink-0 text-muted-foreground hover:text-error"
                  onClick={() => void remove(credential)}
                  disabled={busyId === credential.id}
                  aria-label={`Delete ${credential.label}`}
                >
                  {busyId === credential.id ? (
                    <Spinner size="sm" className="text-current" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
