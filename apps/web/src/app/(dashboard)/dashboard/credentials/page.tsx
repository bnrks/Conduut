"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import { AUTH_METHODS, friendlyTypeLabel } from "@/lib/credential-auth-methods";
import {
  CredentialForm,
  type CredentialSubmission,
} from "@/components/credentials/credential-form";

interface SavedCredential {
  id: string;
  label: string;
  credential_type: string;
  host: string;
  created_at?: string;
}

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
  const [isLoading, setIsLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) {
      setCredentials([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch("/api/credentials", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(await getErrorMessage(response, "Could not load credentials."));
      }
      const data = (await response.json()) as { credentials?: SavedCredential[] };
      setCredentials(data.credentials ?? []);
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

  const handleSubmit = async (submission: CredentialSubmission) => {
    if (!user) throw new Error("Please sign in first.");
    const token = await user.getIdToken();
    const response = await fetch("/api/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        credential_type: submission.credential_type,
        generic_auth_type: submission.generic_auth_type,
        label: submission.label,
        host: submission.host,
        data: submission.data,
      }),
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response, "Credential could not be saved."));
    }
    toast.success("Credential saved.");
    setShowForm(false);
    await load();
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
        <Button size="sm" onClick={() => setShowForm((open) => !open)}>
          <Plus className="h-4 w-4" />
          Add credential
        </Button>
      </div>

      <p className="mb-4 max-w-2xl text-[13px] text-muted-foreground">
        Save the API keys and logins your automations use. When Conduut builds a workflow
        that calls a service, it matches a saved credential by its address and asks you to
        confirm before using it. Secrets are stored only in your own n8n instance.
      </p>

      {showForm && (
        <Card className="mb-6">
          <CardContent className="p-4">
            <CredentialForm methods={AUTH_METHODS} requireHost onSubmit={handleSubmit} />
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
              Add an API key or login so Conduut can authenticate your workflows.
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
                      {friendlyTypeLabel(credential.credential_type)}
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
