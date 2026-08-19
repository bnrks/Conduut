"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AutomationServerSection } from "@/components/settings/automation-server-section";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

type Tab = "profile" | "security" | "preferences" | "automation-server";
type ThemeOption = "light" | "dark" | "system";

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "security", label: "Security" },
  { key: "preferences", label: "Preferences" },
  { key: "automation-server", label: "Automation Server" },
];

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const initialTab = searchParams.get("tab") === "automation-server" ? "automation-server" : "profile";
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();

  const [name, setName] = useState(user?.displayName || "User");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailNotifications, setEmailNotifications] = useState(true);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setName(user?.displayName || "User");
    }, 0);
    return () => window.clearTimeout(timer);
  }, [user?.displayName]);

  useEffect(() => {
    if (searchParams.get("tab") === "automation-server") {
      const timer = window.setTimeout(() => {
        setActiveTab("automation-server");
      }, 0);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [searchParams]);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-medium text-foreground">Settings</h1>

      <div className="mb-6 flex w-fit items-center gap-1 rounded-lg border border-border bg-card p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "rounded-md px-4 py-1.5 text-[14px] font-medium transition-colors",
              activeTab === tab.key ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "profile" ? (
        <Card className="max-w-lg">
          <CardContent className="flex flex-col gap-5 p-6">
            <h2 className="text-[15px] font-medium text-foreground">Profile Information</h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Name</label>
              <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" />
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
      ) : null}

      {activeTab === "security" ? (
        <Card className="max-w-lg">
          <CardContent className="flex flex-col gap-5 p-6">
            <h2 className="text-[15px] font-medium text-foreground">Change Password</h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Current Password</label>
              <Input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} placeholder="Enter current password" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">New Password</label>
              <Input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="Enter new password" />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">Confirm New Password</label>
              <Input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Confirm new password"
                error={confirmPassword.length > 0 && confirmPassword !== newPassword}
              />
              {confirmPassword.length > 0 && confirmPassword !== newPassword ? (
                <p className="text-[12px] text-error">Passwords do not match.</p>
              ) : null}
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
      ) : null}

      {activeTab === "preferences" ? (
        <Card className="max-w-lg">
          <CardContent className="flex flex-col gap-6 p-6">
            <h2 className="text-[15px] font-medium text-foreground">Preferences</h2>

            <div className="flex flex-col gap-2">
              <label className="text-[13px] font-medium text-foreground">Theme</label>
              <div className="flex w-fit items-center gap-1 rounded-lg border border-border bg-muted p-1">
                {(["light", "dark", "system"] as ThemeOption[]).map((nextTheme) => (
                  <button
                    key={nextTheme}
                    onClick={() => setTheme(nextTheme)}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-[13px] font-medium capitalize transition-colors",
                      theme === nextTheme ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {nextTheme.charAt(0).toUpperCase() + nextTheme.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-medium text-foreground">Email Notifications</p>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  Receive emails about workflow errors and usage alerts.
                </p>
              </div>
              <button
                role="switch"
                aria-checked={emailNotifications}
                onClick={() => setEmailNotifications((value) => !value)}
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

            <div className="flex justify-end border-t border-border pt-1">
              <Button size="sm" onClick={() => console.log("Save preferences:", { theme, emailNotifications })}>
                Save Preferences
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "automation-server" ? <AutomationServerSection /> : null}
    </div>
  );
}
