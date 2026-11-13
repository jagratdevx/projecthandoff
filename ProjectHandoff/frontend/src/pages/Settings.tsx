import { useEffect, useState } from "react";
import { AlertTriangle, Cloud, HardDrive, KeyRound, LogOut, Monitor, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import { useTheme } from "../hooks/useTheme";
import { Button, Card, CardHeader, Field, Input, PageHeader } from "../components/ui";import { formatTime } from "../lib/format";

interface DriveStatus {
  storage_mode: string;
  drive_configured: boolean;
  authorized?: boolean;
  account?: string | null;
  message?: string;
  authorize_url?: string | null;
}

export function Settings() {
  const { user, refresh } = useAuth();
  const { theme, toggle } = useTheme();
  const toast = useToast();

  const [name, setName] = useState(user?.name ?? "");
  const [savingName, setSavingName] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [drive, setDrive] = useState<DriveStatus | null>(null);
  const [driveLoading, setDriveLoading] = useState(true);
  const [authorizing, setAuthorizing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<DriveStatus>("/api/drive/status")
      .then((status) => {
        if (!cancelled) setDrive(status);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setDriveLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const saveName = async (event: React.FormEvent) => {
    event.preventDefault();
    setSavingName(true);
    try {
      await api("/api/auth/me", { method: "PATCH", body: { name } });
      await refresh();
      toast.push("success", "Profile updated");
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Update failed");
    } finally {
      setSavingName(false);
    }
  };

  const changePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setSavingPassword(true);
    try {
      await api("/api/auth/password", { method: "POST", body: { current_password: currentPassword, new_password: newPassword } });
      setCurrentPassword("");
      setNewPassword("");
      toast.push("success", "Password changed");
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Password change failed");
    } finally {
      setSavingPassword(false);
    }
  };

  const authorizeDrive = async () => {
    setAuthorizing(true);
    try {
      const { authorize_url: url } = await api<{ authorize_url: string }>("/api/drive/oauth/start?frontend_redirect=/settings");
      window.location.href = url;
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not start authorization");
      setAuthorizing(false);
    }
  };

  const isDriveMode = drive?.storage_mode === "drive";

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" subtitle="Your profile, appearance and system status" />

      {/* Profile */}
      <Card className="mb-6">
        <CardHeader title="Profile" />
        <form onSubmit={saveName} className="space-y-4 p-5">
          <div className="flex flex-wrap items-center gap-4">
            <Field label="Display name">
              <Input required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Email">
              <Input value={user?.email ?? ""} disabled aria-disabled />
            </Field>
            <Field label="Team role">
              <Input value={user?.role ?? ""} disabled aria-disabled />
            </Field>
          </div>
          <div className="flex justify-end">
            <Button type="submit" loading={savingName}>
              Save profile
            </Button>
          </div>
        </form>
      </Card>

      {/* Password */}
      <Card className="mb-6">
        <CardHeader title="Password" />
        <form onSubmit={changePassword} className="space-y-4 p-5">
          <div className="flex flex-wrap items-center gap-4">
            <Field label="Current password">
              <Input type="password" required autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
            </Field>
            <Field label="New password" hint="At least 8 characters.">
              <Input type="password" required minLength={8} autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </Field>
          </div>
          <div className="flex justify-end">
            <Button type="submit" loading={savingPassword} variant="secondary">
              <KeyRound className="h-4 w-4" aria-hidden /> Change password
            </Button>
          </div>
        </form>
      </Card>

      {/* Appearance */}
      <Card className="mb-6">
        <CardHeader title="Appearance" />
        <div className="flex items-center justify-between p-5">
          <div className="flex items-center gap-3">
            <Monitor className="h-4 w-4 text-zinc-400" aria-hidden />
            <div>
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Theme</p>
              <p className="text-xs text-zinc-500">Currently using {theme} mode.</p>
            </div>
          </div>
          <Button variant="secondary" onClick={toggle}>
            Switch to {theme === "dark" ? "light" : "dark"}
          </Button>
        </div>
      </Card>

      {/* Storage & sync */}
      <Card className="mb-6">
        <CardHeader title="Storage & synchronization" />
        <div className="p-5">
          {driveLoading ? (
            <p className="text-sm text-zinc-500">Checking storage status…</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  {isDriveMode ? <Cloud className="h-4 w-4 text-zinc-400" aria-hidden /> : <HardDrive className="h-4 w-4 text-zinc-400" aria-hidden />}
                  <div>
                    <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {isDriveMode ? "Google Drive (organizer account)" : "Local development storage"}
                    </p>
                    <p className="text-xs text-zinc-500">{drive?.message ?? "All structured data lives in CSV files in Drive; uploads are stored there too."}</p>
                  </div>
                </div>
                {isDriveMode && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${drive?.authorized ? "bg-emerald-500" : "bg-red-500"}`}
                      aria-hidden
                    />
                    {drive?.authorized ? "Connected" : "Not connected"}
                  </span>
                )}
              </div>

              {!isDriveMode && (
                <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3 dark:border-amber-800 dark:bg-amber-950/60">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden />
                  <p className="text-sm text-amber-900 dark:text-amber-200">
                    This backend is running in explicit local development mode. Data is stored on this machine only —
                    it is NOT synchronized through Google Drive. Production use requires PH_STORAGE_MODE=drive and
                    organizer OAuth authorization.
                  </p>
                </div>
              )}

              {isDriveMode && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 px-3.5 py-3 dark:border-zinc-800">
                  <div className="text-sm">
                    <p className="font-medium text-zinc-900 dark:text-zinc-100">
                      Drive authorization: {drive?.authorized ? "connected" : "not connected"}
                    </p>
                    <p className="text-xs text-zinc-500">
                      {drive?.authorized ? `Authorized as ${drive.account ?? "organizer"}` : "The organizer must authorize once; all team members share this connection."}
                    </p>
                  </div>
                  {!drive?.authorized && (
                    <Button onClick={() => void authorizeDrive()} loading={authorizing}>
                      <RefreshCw className="h-4 w-4" aria-hidden /> Authorize Google Drive
                    </Button>
                  )}
                </div>
              )}

              <div className="rounded-lg border border-zinc-200 px-3.5 py-3 text-xs text-zinc-500 dark:border-zinc-800">
                <p>RefreshCw-style sync: the app polls the server every 10–15 seconds, refreshes immediately after your actions, and shows the last sync time in the top bar. A hosted backend must stay reachable for live updates.</p>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Session */}
      <Card>
        <CardHeader title="Session" />
        <div className="flex items-center justify-between p-5">
          <div>
            <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Signed in as {user?.email}</p>
            <p className="text-xs text-zinc-500">Last synchronized with the server at {formatTime(Date.now())}</p>
          </div>
          <Button variant="secondary" onClick={() => { window.location.href = "/login"; }}>
            <LogOut className="h-4 w-4" aria-hidden /> Sign out of this browser
          </Button>
        </div>
      </Card>
    </div>
  );
}
