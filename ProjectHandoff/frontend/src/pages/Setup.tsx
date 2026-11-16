import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Cloud, ExternalLink, RefreshCw } from "lucide-react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Button, Card, Field, Input, Spinner } from "../components/ui";
import { useToast } from "../state/ToastContext";

interface SetupStatus {
  storage_mode: string;
  client_configured: boolean;
  authorized: boolean;
  needs_setup: boolean;
  redirect_uri: string;
}

/**
 * First-run setup wizard (public route).
 *
 * Shown when the backend runs in Google Drive mode but has not been connected
 * yet: enter the Google OAuth client credentials once, authorize Drive, then
 * continue to account creation. Redirects away when nothing needs setting up.
 */
export function Setup() {
  const navigate = useNavigate();
  const toast = useToast();

  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [form, setForm] = useState({ client_id: "", client_secret: "" });
  const [saving, setSaving] = useState(false);
  const [authorizing, setAuthorizing] = useState(false);

  const params = new URLSearchParams(window.location.search);
  const driveStatus = params.get("drive"); // "connected" | "error" | null

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api<SetupStatus>("/api/setup/status", { skipAuth: true }));
    } catch {
      setStatus(null); // backend unreachable — keep the spinner off, show an error below
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus, driveStatus]);

  // Re-check once Google bounces back to us.
  useEffect(() => {
    if (driveStatus === "connected") void loadStatus();
  }, [driveStatus, loadStatus]);

  if (status && !status.needs_setup) {
    // Nothing to configure — send people to the normal entry points.
    return <Navigate to="/login" replace />;
  }

  const saveCredentials = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api("/api/setup/drive-client", { method: "POST", body: form, skipAuth: true });
      toast.push("success", "Google OAuth client saved");
      await loadStatus();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not save the credentials");
    } finally {
      setSaving(false);
    }
  };

  const startAuthorization = async () => {
    setAuthorizing(true);
    try {
      const { authorize_url } = await api<{ authorize_url: string }>(
        "/api/drive/oauth/start?frontend_redirect=/setup",
        { skipAuth: true },
      );
      window.location.href = authorize_url;
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not start the authorization");
      setAuthorizing(false);
    }
  };

  const authorized = status?.authorized ?? false;

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4 dark:bg-zinc-950">
      <div className="w-full max-w-lg space-y-4">
        <div className="text-center">
          <Cloud className="mx-auto h-10 w-10 text-indigo-500" aria-hidden />
          <h1 className="mt-3 text-2xl font-semibold text-zinc-900 dark:text-zinc-100">Set up ProjectHandoff</h1>
          <p className="mt-1 text-sm text-zinc-500">
            One-time setup connecting the app to Google Drive — all team data will live in your Drive.
          </p>
        </div>

        {!status ? (
          <Card className="flex items-center justify-center gap-3 p-8 text-sm text-zinc-500">
            <Spinner className="h-5 w-5" /> Contacting the server…
          </Card>
        ) : driveStatus === "error" && !authorized ? (
          <Card className="p-6">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" aria-hidden />
              <div>
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Google authorization failed</p>
                <p className="mt-1 text-sm text-zinc-500">
                  The sign-in with Google didn't complete. You can simply try again — nothing was saved.
                </p>
                <Button className="mt-4" onClick={() => void startAuthorization()} loading={authorizing}>
                  <RefreshCw className="h-4 w-4" aria-hidden /> Try again
                </Button>
              </div>
            </div>
          </Card>
        ) : authorized ? (
          <Card className="p-6 text-center">
            <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-500" aria-hidden />
            <p className="mt-3 text-sm font-medium text-zinc-900 dark:text-zinc-100">Google Drive is connected</p>
            <p className="mt-1 text-sm text-zinc-500">
              Everything is ready. Create the organizer account next — it becomes the team owner.
            </p>
            <Button className="mt-5 w-full" onClick={() => navigate("/register")}>
              Create your account
            </Button>
          </Card>
        ) : !status.client_configured ? (
          <Card className="p-6">
            <form onSubmit={saveCredentials} className="space-y-4">
              <div>
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Step 1 · Google OAuth client</p>
                <p className="mt-1 text-xs text-zinc-500">
                  In the Google Cloud console (APIs &amp; Services → Credentials) create an{" "}
                  <strong>OAuth client ID</strong> of type <strong>Web application</strong>, enable the{" "}
                  <strong>Google Drive API</strong>, and add this authorized redirect URI:
                </p>
                <code className="mt-2 block break-all rounded-md border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-xs text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                  {status.redirect_uri}
                </code>
              </div>
              <Field label="Client ID">
                <Input
                  required
                  value={form.client_id}
                  onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                  placeholder="1234567890-abc123.apps.googleusercontent.com"
                />
              </Field>
              <Field label="Client secret">
                <Input
                  required
                  type="password"
                  value={form.client_secret}
                  onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
                  placeholder="GOCSPX-…"
                />
              </Field>
              <p className="text-xs text-zinc-500">
                Stored only on this server (gitignored file) — never in the shared Drive data.
              </p>
              <Button type="submit" loading={saving} className="w-full">
                Save and continue
              </Button>
            </form>
          </Card>
        ) : (
          <Card className="p-6 text-center">
            <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-500" aria-hidden />
            <p className="mt-3 text-sm font-medium text-zinc-900 dark:text-zinc-100">Step 2 · Authorize Google Drive</p>
            <p className="mt-1 text-sm text-zinc-500">
              Sign in with the Google account that owns the team's Drive folders. This organizer connection is
              shared by the whole team and only needs to happen once.
            </p>
            <Button className="mt-5 w-full" onClick={() => void startAuthorization()} loading={authorizing}>
              <ExternalLink className="h-4 w-4" aria-hidden /> Connect Google Drive
            </Button>
          </Card>
        )}
      </div>
    </div>
  );
}
