"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

type Tab = "profile" | "security" | "preferences";

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "security", label: "Security" },
  { key: "preferences", label: "Preferences" },
];

type ThemeOption = "light" | "dark" | "system";
// Theme is controlled by useTheme hook (persists to localStorage + applies .dark class)

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("profile");

  // Profile state
  const [name, setName] = useState("Burak");

  // Security state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Preferences state
  const { theme, setTheme } = useTheme();
  const [emailNotifications, setEmailNotifications] = useState(true);

  return (
    <div>
      <h1 className="text-2xl font-medium text-foreground mb-6">Settings</h1>

      {/* Tab navigation */}
      <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-card w-fit mb-6">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "px-4 py-1.5 rounded-md text-[14px] font-medium transition-colors",
              activeTab === tab.key
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Profile tab */}
      {activeTab === "profile" && (
        <Card className="max-w-lg">
          <CardContent className="p-6 flex flex-col gap-5">
            <h2 className="text-[15px] font-medium text-foreground">
              Profile Information
            </h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">
                Name
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">
                Email
              </label>
              <Input
                value="burak@example.com"
                disabled
                className="bg-muted"
              />
              <p className="text-[12px] text-muted-foreground">
                Email cannot be changed after registration.
              </p>
            </div>
            <div className="flex justify-end pt-1">
              <Button
                size="sm"
                onClick={() => console.log("Save profile:", name)}
              >
                Save Changes
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Security tab */}
      {activeTab === "security" && (
        <Card className="max-w-lg">
          <CardContent className="p-6 flex flex-col gap-5">
            <h2 className="text-[15px] font-medium text-foreground">
              Change Password
            </h2>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">
                Current Password
              </label>
              <Input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Enter current password"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">
                New Password
              </label>
              <Input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Enter new password"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-medium text-foreground">
                Confirm New Password
              </label>
              <Input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Confirm new password"
                error={
                  confirmPassword.length > 0 &&
                  confirmPassword !== newPassword
                }
              />
              {confirmPassword.length > 0 && confirmPassword !== newPassword && (
                <p className="text-[12px] text-error">
                  Passwords do not match.
                </p>
              )}
            </div>
            <div className="flex justify-end pt-1">
              <Button
                size="sm"
                disabled={
                  !currentPassword ||
                  !newPassword ||
                  newPassword !== confirmPassword
                }
                onClick={() => console.log("Update password")}
              >
                Update Password
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Preferences tab */}
      {activeTab === "preferences" && (
        <Card className="max-w-lg">
          <CardContent className="p-6 flex flex-col gap-6">
            <h2 className="text-[15px] font-medium text-foreground">
              Preferences
            </h2>

            {/* Theme */}
            <div className="flex flex-col gap-2">
              <label className="text-[13px] font-medium text-foreground">
                Theme
              </label>
              <div className="flex items-center gap-1 rounded-lg border border-border p-1 bg-muted w-fit">
                {(["light", "dark", "system"] as ThemeOption[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTheme(t)}
                    className={cn(
                      "px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors capitalize",
                      theme === t
                        ? "bg-card text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            {/* Email notifications */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-medium text-foreground">
                  Email Notifications
                </p>
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
              <Button
                size="sm"
                onClick={() => console.log("Save preferences:", { theme, emailNotifications })}
              >
                Save Preferences
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
