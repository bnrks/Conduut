"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useTheme } from "@/hooks/use-theme";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

type Tab = "profile" | "security" | "preferences" | "assistant-connections";
type ThemeOption = "light" | "dark" | "system";
type ProviderPreset = "openai" | "google" | "anthropic" | "openrouter" | "groq" | "custom";

interface ProviderConnection {
  provider: string;
  masked_key: string;
}

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "security", label: "Security" },
  { key: "preferences", label: "Preferences" },
  { key: "assistant-connections", label: "Assistant Connections" },
];

const PROVIDER_PRESETS: { key: ProviderPreset; label: string; providerValue: string }[] = [
  { key: "openai", label: "OpenAI", providerValue: "openai" },
  { key: "google", label: "Gemini (Google)", providerValue: "google" },
  { key: "anthropic", label: "Claude (Anthropic)", providerValue: "anthropic" },
  { key: "openrouter", label: "OpenRouter", providerValue: "openrouter" },
  { key: "groq", label: "Groq Cloud", providerValue: "groq" },
  { key: "custom", label: "Custom", providerValue: "" },
];

const DEFAULT_MODELS_BY_PROVIDER: Record<string, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-3-5-sonnet-latest",
  google: "gemini-1.5-flash",
  groq: "llama-3.3-70b-versatile",
  openrouter: "openai/gpt-4o-mini",
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("profile");
  const { user } = useAuth();

  // Profile state
  const [name, setName] = useState(user?.displayName || "User");

  // Security state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Preferences state
  const { theme, setTheme } = useTheme();
  const [emailNotifications, setEmailNotifications] = useState(true);

  // Assistant connections state
  const [providerPreset, setProviderPreset] = useState<ProviderPreset>("openai");
  const [customProvider, setCustomProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [isLoadingProviders, setIsLoadingProviders] = useState(false);
  const [isSavingProvider, setIsSavingProvider] = useState(false);
  const [removingProvider, setRemovingProvider] = useState<string | null>(null);
  const [verifyingProvider, setVerifyingProvider] = useState<string | null>(null);
  const [verifyResults, setVerifyResults] = useState<Record<string, boolean | null>>({});

  const resolvedProvider = useMemo(() => {
    if (providerPreset === "custom") return customProvider.trim();
    return PROVIDER_PRESETS.find((item) => item.key === providerPreset)?.providerValue ?? "openai";
  }, [customProvider, providerPreset]);

  const canAddProvider = resolvedProvider.length > 0 && apiKey.trim().length > 0;

  const getErrorMessage = async (response: Response, fallback: string): Promise<string> => {
    const payload = (await response.json().catch(() => null)) as { detail?: string; message?: string } | null;
    return payload?.detail || payload?.message || fallback;
  };

  const loadProviders = async () => {
    if (!user) return;

    setIsLoadingProviders(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch("/api/settings/llm/providers", {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) throw new Error(await getErrorMessage(response, "Could not load provider connections."));
      const data = (await response.json()) as { providers: ProviderConnection[] };
      setConnections(data.providers || []);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not load provider connections.");
    } finally {
      setIsLoadingProviders(false);
    }
  };

  const addProvider = async () => {
    if (!user || !canAddProvider) return;

    setIsSavingProvider(true);
    try {
      const token = await user.getIdToken();
      const provider = resolvedProvider;
      const model = DEFAULT_MODELS_BY_PROVIDER[provider] || "gpt-4o-mini";

      const llmResponse = await fetch("/api/settings/llm", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          provider,
          model,
          api_key: apiKey.trim(),
        }),
      });

      if (!llmResponse.ok) throw new Error(await getErrorMessage(llmResponse, "Could not update active model settings."));

      const response = await fetch("/api/settings/llm/providers", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          provider,
          api_key: apiKey.trim(),
        }),
      });

      if (!response.ok) throw new Error(await getErrorMessage(response, "Could not save provider connection."));
      const data = (await response.json()) as { providers: ProviderConnection[] };
      setConnections(data.providers || []);
      setApiKey("");
      if (providerPreset !== "custom") {
        setCustomProvider("");
      }
      toast.success(`${provider} connected and set as active model.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save provider connection.");
    } finally {
      setIsSavingProvider(false);
    }
  };

  const verifyProvider = async (provider: string) => {
    if (!user) return;
    setVerifyingProvider(provider);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/settings/llm/providers/${encodeURIComponent(provider)}/verify`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = (await response.json()) as { valid: boolean; error?: string };
      setVerifyResults((prev) => ({ ...prev, [provider]: data.valid }));
      if (data.valid) {
        toast.success(`${provider} API key is valid.`);
      } else {
        toast.error(`${provider}: ${data.error ?? "Invalid API key"}`);
      }
    } catch {
      toast.error("Could not verify provider.");
    } finally {
      setVerifyingProvider(null);
    }
  };

  const removeProvider = async (provider: string) => {
    if (!user) return;

    setRemovingProvider(provider);
    try {
      const token = await user.getIdToken();
      const response = await fetch(`/api/settings/llm/providers/${encodeURIComponent(provider)}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) throw new Error(await getErrorMessage(response, "Could not remove provider connection."));
      const data = (await response.json()) as { providers: ProviderConnection[] };
      setConnections(data.providers || []);
      toast.success(`${provider} removed.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not remove provider connection.");
    } finally {
      setRemovingProvider(null);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-medium text-foreground mb-6">Settings</h1>

      <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-card w-fit mb-6">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key);
              if (tab.key === "assistant-connections") {
                void loadProviders();
              }
            }}
            className={cn(
              "px-4 py-1.5 rounded-md text-[14px] font-medium transition-colors",
              activeTab === tab.key ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "profile" && (
        <Card className="max-w-lg">
          <CardContent className="p-6 flex flex-col gap-5">
            <h2 className="text-[15px] font-medium text-foreground">Profile Information</h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Name</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Email</label>
              <Input value={user?.email ?? ""} disabled className="bg-muted" />
              <p className="text-[12px] text-muted-foreground">Email cannot be changed after registration.</p>
            </div>
            <div className="flex justify-end pt-1">
              <Button size="sm" onClick={() => console.log("Save profile:", name)}>
                Save Changes
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "security" && (
        <Card className="max-w-lg">
          <CardContent className="p-6 flex flex-col gap-5">
            <h2 className="text-[15px] font-medium text-foreground">Change Password</h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Current Password</label>
              <Input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Enter current password"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">New Password</label>
              <Input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Enter new password"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Confirm New Password</label>
              <Input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Confirm new password"
                error={confirmPassword.length > 0 && confirmPassword !== newPassword}
              />
              {confirmPassword.length > 0 && confirmPassword !== newPassword && (
                <p className="text-[12px] text-error">Passwords do not match.</p>
              )}
            </div>
            <div className="flex justify-end pt-1">
              <Button
                size="sm"
                disabled={!currentPassword || !newPassword || newPassword !== confirmPassword}
                onClick={() => console.log("Update password")}
              >
                Update Password
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "preferences" && (
        <Card className="max-w-lg">
          <CardContent className="p-6 flex flex-col gap-6">
            <h2 className="text-[15px] font-medium text-foreground">Preferences</h2>

            <div className="flex flex-col gap-2">
              <label className="text-[13px] font-medium text-foreground">Theme</label>
              <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-muted w-fit">
                {(["light", "dark", "system"] as ThemeOption[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTheme(t)}
                    className={cn(
                      "px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors capitalize",
                      theme === t ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-medium text-foreground">Email Notifications</p>
                <p className="text-[12px] text-muted-foreground mt-0.5">
                  Receive emails about workflow errors and usage alerts.
                </p>
              </div>
              <button
                role="switch"
                aria-checked={emailNotifications}
                onClick={() => setEmailNotifications((v) => !v)}
                className={cn(
                  "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  emailNotifications ? "bg-conduut-500" : "bg-gray-200"
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm ring-0 transition-transform duration-200",
                    emailNotifications ? "translate-x-5" : "translate-x-0"
                  )}
                />
              </button>
            </div>

            <div className="flex justify-end pt-1 border-t border-border">
              <Button size="sm" onClick={() => console.log("Save preferences:", { theme, emailNotifications })}>
                Save Preferences
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "assistant-connections" && (
        <div className="max-w-lg flex flex-col gap-4">
          <Card>
            <CardContent className="p-6 flex flex-col gap-5">
              <h2 className="text-[15px] font-medium text-foreground">Connect AI Providers</h2>

              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-medium text-foreground">Provider</label>
                <select
                  value={providerPreset}
                  onChange={(e) => {
                    const next = e.target.value as ProviderPreset;
                    setProviderPreset(next);
                    if (next !== "custom") {
                      setCustomProvider("");
                    }
                  }}
                  className="h-9 rounded-md border border-border bg-background px-3 text-[14px] text-foreground"
                >
                  {PROVIDER_PRESETS.map((provider) => (
                    <option key={provider.key} value={provider.key}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </div>

              {providerPreset === "custom" && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-[13px] font-medium text-foreground">Custom Provider Slug</label>
                  <Input
                    placeholder="e.g. together_ai, fireworks_ai"
                    value={customProvider}
                    onChange={(e) => setCustomProvider(e.target.value)}
                  />
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-medium text-foreground">API Key</label>
                <Input
                  type="password"
                  placeholder="Paste provider API key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </div>

              <div className="flex justify-end pt-1 border-t border-border">
                <Button size="sm" onClick={addProvider} disabled={!canAddProvider || isSavingProvider || isLoadingProviders}>
                  {isSavingProvider ? "Adding..." : "Add Provider"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6 flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h3 className="text-[15px] font-medium text-foreground">Connected Providers</h3>
                <Button size="sm" variant="outline" onClick={loadProviders} disabled={isLoadingProviders}>
                  {isLoadingProviders ? "Refreshing..." : "Refresh"}
                </Button>
              </div>

              {connections.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">No provider connected yet.</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {connections.map((item) => (
                    <div key={item.provider} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-[13px] font-medium text-foreground">{item.provider}</p>
                          {verifyResults[item.provider] === true && (
                            <span className="text-[11px] font-medium text-success bg-success-light px-1.5 py-0.5 rounded">Valid</span>
                          )}
                          {verifyResults[item.provider] === false && (
                            <span className="text-[11px] font-medium text-error bg-error-light px-1.5 py-0.5 rounded">Invalid</span>
                          )}
                        </div>
                        <p className="text-[12px] text-muted-foreground">{item.masked_key}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => verifyProvider(item.provider)}
                          disabled={verifyingProvider === item.provider}
                        >
                          {verifyingProvider === item.provider ? "Checking..." : "Verify"}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => removeProvider(item.provider)}
                          disabled={removingProvider === item.provider}
                        >
                          {removingProvider === item.provider ? "Removing..." : "Remove"}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
