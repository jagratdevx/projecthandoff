import { useEffect, useState } from "react";
import { Check, Copy, ExternalLink, FolderOpen, Link2, RefreshCw, Send, Share2, Trash2, UserPlus } from "lucide-react";
import { api } from "../api/client";
import type { Invitation, Team, TeamDriveStatus, User } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  SkeletonList,
  Textarea,
} from "../components/ui";
import { formatDate } from "../lib/format";

const DRIVE_SETUP_HELP =
  "One-time, free (~10 minutes): console.cloud.google.com → create a project → enable the Google Drive API → OAuth consent screen (External, add yourself as test user) → Credentials → OAuth client ID → Web application. Paste the redirect URI below as an Authorized redirect URI, then copy the client ID and secret here.";

export function TeamPage() {
  const { user, refresh } = useAuth();
  const toast = useToast();

  const { data, loading, reload } = useResource<{ team: Team | null; members: User[] }>(
    () => api("/api/teams/mine"),
    [],
    20000,
  );

  const team = data?.team ?? null;
  const isAdmin = user?.role === "owner" || user?.role === "admin";
  const useInvites = !!team && isAdmin;

  const { data: invitations, reload: reloadInvites } = useResource<Invitation[]>(
    () => (team ? api(`/api/teams/${team.team_id}/invitations`) : Promise.resolve([])),
    [team?.team_id],
    0,
  );

  const { data: driveStatus, loading: driveLoading, reload: reloadDriveStatus } = useResource<TeamDriveStatus>(
    () => (team ? api(`/api/teams/${team.team_id}/drive/status`) : Promise.resolve({
      storage_mode: "local", client_configured: false, connected: false, account: null, folder: null,
    })),
    [team?.team_id],
    0,
  );

  // One-time OAuth return from Google (?drive=connected|error&reason=…)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("drive") === "connected") {
      toast.push("success", "Google Drive connected — now paste your team folder link to finish");
      reloadDriveStatus();
    } else if (params.get("drive") === "error") {
      const reason = params.get("reason");
      toast.push("error", reason === "denied"
        ? "Google authorization was cancelled — click Connect again to retry"
        : "Google authorization failed — please try again from the team page");
    }
    if (params.has("drive")) {
      params.delete("drive");
      params.delete("reason");
      const clean = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${clean ? `?${clean}` : ""}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [teamForm, setTeamForm] = useState({ name: "", description: "", drive_client_id: "", drive_client_secret: "" });
  const [redirectUri, setRedirectUri] = useState("");
  useEffect(() => {
    api<{ redirect_uri: string }>("/api/teams/drive/oauth/defaults")
      .then((d) => setRedirectUri(d.redirect_uri))
      .catch(() => {});
  }, []);

  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState({ name: "", description: "" });
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({ email: "", role: "member" });
  const [lastInvite, setLastInvite] = useState<Invitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState<User | null>(null);
  const [saving, setSaving] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [folderForm, setFolderForm] = useState({ drive_folder_url: "" });
  const [linking, setLinking] = useState(false);

  // ------------------------------------------------------------------ create team
  if (!team) {
    return (
      <div>
        <PageHeader title="Team" subtitle="Create a team to unlock projects, tasks and handovers" />
        {loading ? (
          <SkeletonList rows={2} />
        ) : (
          <Card className="mx-auto max-w-md p-6">
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                setSaving(true);
                try {
                  const created = await api<Team & { authorize_url?: string; next_step?: string }>("/api/teams", {
                    method: "POST",
                    body: teamForm,
                  });
                  if (created.authorize_url) {
                    // One-time Google consent for the team owner — members
                    // never see this. Google returns to /team afterwards.
                    await refresh();
                    toast.push("success", "Team created — taking you to Google to connect your Drive…");
                    window.location.href = created.authorize_url;
                    return;
                  }
                  toast.push("success", "Team created");
                  await refresh();
                  void reload();
                } catch (err) {
                  toast.push("error", err instanceof Error ? err.message : "Failed to create team");
                } finally {
                  setSaving(false);
                }
              }}
              className="space-y-4"
            >
              <Field label="Team name">
                <Input required value={teamForm.name} onChange={(e) => setTeamForm({ ...teamForm, name: e.target.value })} placeholder="Robotics Club" />
              </Field>
              <Field label="Description">
                <Textarea value={teamForm.description} onChange={(e) => setTeamForm({ ...teamForm, description: e.target.value })} placeholder="What does this team do?" />
              </Field>
              <div className="rounded-lg border border-brand-200 bg-brand-50/60 p-3.5 dark:border-brand-900 dark:bg-brand-950/40">
                <p className="mb-3 text-sm font-medium text-brand-900 dark:text-brand-200">
                  Connect your Google Drive — all team files live in a folder you own
                </p>
                <div className="space-y-3">
                  <Field label="Google OAuth client ID">
                    <Input
                      required
                      value={teamForm.drive_client_id}
                      onChange={(e) => setTeamForm({ ...teamForm, drive_client_id: e.target.value })}
                      placeholder="1234….apps.googleusercontent.com"
                    />
                  </Field>
                  <Field label="Google OAuth client secret">
                    <Input
                      required
                      type="password"
                      value={teamForm.drive_client_secret}
                      onChange={(e) => setTeamForm({ ...teamForm, drive_client_secret: e.target.value })}
                      placeholder="GOCSPX-…"
                    />
                  </Field>
                  <div className="text-xs text-stone-600 dark:text-stone-400">
                    <p className="font-medium">Add this redirect URI in your Google Cloud console:</p>
                    <code className="mt-1 block break-all rounded bg-stone-100 px-2 py-1 font-mono text-[11px] dark:bg-stone-800">
                      {redirectUri || "loading…"}
                    </code>
                  </div>
                  <details className="text-xs text-stone-600 dark:text-stone-400">
                    <summary className="cursor-pointer font-medium">How do I get these? (one-time, ~10 min, free)</summary>
                    <p className="mt-2 leading-relaxed">{DRIVE_SETUP_HELP}</p>
                  </details>
                </div>
              </div>
              <Button type="submit" loading={saving} className="w-full">
                <UserPlus className="h-4 w-4" aria-hidden /> Create team &amp; connect Drive
              </Button>
              <p className="text-center text-xs text-stone-500">
                Members never need a Google account for this — only you, once. Have an invite link instead? Open it and register there.
              </p>
            </form>
          </Card>
        )}
      </div>
    );
  }

  const members = data?.members ?? [];
  const drive = driveStatus ?? null;
  const needsFolderLink =
    isAdmin && !!drive?.connected && !drive.via_host && !team.drive_folder_id;

  const linkFolder = async (event: React.FormEvent) => {
    event.preventDefault();
    setLinking(true);
    try {
      await api(`/api/teams/${team.team_id}/drive/folder`, { method: "POST", body: folderForm });
      toast.push("success", "Drive folder linked — everything the team stores now lives there");
      setFolderOpen(false);
      setFolderForm({ drive_folder_url: "" });
      await refresh();
      void reload();
      reloadDriveStatus();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Linking failed");
    } finally {
      setLinking(false);
    }
  };

  const reconnectDrive = async () => {
    try {
      const result = await api<{ authorize_url: string }>(`/api/teams/${team.team_id}/drive/reconnect`, { method: "POST" });
      window.location.href = result.authorize_url;
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Reconnect failed");
    }
  };

  const saveTeamEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api(`/api/teams/${team.team_id}`, { method: "PATCH", body: editForm });
      toast.push("success", "Team updated");
      setEditOpen(false);
      await refresh();
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Update failed");
    } finally {
      setSaving(false);
    }
  };

  const sendInvite = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      const invitation = await api<Invitation>(`/api/teams/${team.team_id}/invitations`, {
        method: "POST",
        body: inviteForm,
      });
      toast.push("success", "Invitation created — share the link");
      setLastInvite(invitation);
      setInviteOpen(false);
      setInviteForm({ email: "", role: "member" });
      void reloadInvites();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Failed to create invitation");
    } finally {
      setSaving(false);
    }
  };

  const revokeInvite = async (invitation: Invitation) => {
    try {
      await api(`/api/teams/${team.team_id}/invitations/${invitation.invitation_id}/revoke`, { method: "POST" });
      toast.push("success", "Invitation revoked");
      void reloadInvites();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Revoke failed");
    }
  };

  const removeMember = async (member: User) => {
    try {
      await api(`/api/teams/${team.team_id}/members/${member.user_id}`, { method: "DELETE" });
      toast.push("success", `${member.name} removed from the team`);
      setRemoveConfirm(null);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Removal failed");
    }
  };

  const updateRole = async (member: User, role: string) => {
    try {
      await api(`/api/teams/${team.team_id}/members/${member.user_id}`, { method: "PATCH", body: { role } });
      toast.push("success", `${member.name} is now ${role}`);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Role update failed");
    }
  };

  const shareFolder = async () => {
    try {
      const result = await api<{ shared: number; failed: string[]; members: number }>(
        `/api/teams/${team.team_id}/drive/share`,
        { method: "POST" },
      );
      if (result.failed.length) {
        toast.push("error", `Shared with ${result.shared}/${result.members} — could not grant: ${result.failed.join(", ")}`);
      } else {
        toast.push("success", `Folder shared with all ${result.members} members`);
      }
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Sharing failed");
    }
  };

  return (
    <div>
      <PageHeader
        title={team.name}
        subtitle={team.description || "No description"}
        actions={
          isAdmin && (
            <Button
              variant="secondary"
              onClick={() => {
                setEditForm({ name: team.name, description: team.description });
                setEditOpen(true);
              }}
            >
              Edit team
            </Button>
          )
        }
      />

      {/* Google Drive connection — admins manage it, members just see the folder */}
      {driveLoading && !driveStatus && (
        <Card className="mb-6">
          <CardHeader title="Google Drive" />
          <div className="p-5">
            <SkeletonList rows={2} />
          </div>
        </Card>
      )}
      {drive?.storage_mode === "drive" && (
        <Card className="mb-6">
          <CardHeader
            title="Google Drive"
            action={
              isAdmin && (
                <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
                  {drive.connected && (
                    <Button variant="secondary" className="w-full sm:w-auto" onClick={() => { setFolderForm({ drive_folder_url: team.drive_folder_url ?? "" }); setFolderOpen(true); }}>
                      <FolderOpen className="h-4 w-4" aria-hidden /> {team.drive_folder_id ? "Change folder" : "Link folder"}
                    </Button>
                  )}
                  {!drive.connected && drive.client_configured && (
                    <Button variant="secondary" className="w-full sm:w-auto" onClick={() => void reconnectDrive()}>
                      <RefreshCw className="h-4 w-4" aria-hidden /> Reconnect Google
                    </Button>
                  )}
                  {drive.connected && team.drive_folder_id && (
                    <Button variant="secondary" className="w-full sm:w-auto" onClick={() => void shareFolder()}>
                      <Share2 className="h-4 w-4" aria-hidden /> Share with all members
                    </Button>
                  )}
                </div>
              )
            }
          />
          <div className="space-y-3 px-5 py-4">
            {drive.connected ? (
              <p className="flex items-start gap-2 text-sm text-stone-700 dark:text-stone-300">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden />
                {drive.via_host
                  ? `Running on the organizer's Google Drive${drive.account ? ` (${drive.account})` : ""} — everything syncs automatically. Optionally connect the team's own Drive below.`
                  : `Connected to Google Drive${drive.account ? ` as ${drive.account}` : ""} — you approve this once; the team stays connected.`}
              </p>
            ) : (
              <p className="text-sm text-amber-600 dark:text-amber-400">
                {drive.client_configured
                  ? "Google Drive is not connected yet — reconnect to store the team's files in your own Drive folder."
                  : "This team was created without a Google Drive connection (legacy). Data is stored on the app server."}
              </p>
            )}

            {team.drive_folder_id ? (
              <div className="flex flex-wrap items-center gap-3">
                <FolderOpen className="h-5 w-5 shrink-0 text-brand-500" aria-hidden />
                <a
                  href={team.drive_folder_url || `https://drive.google.com/drive/folders/${team.drive_folder_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-w-0 items-center gap-1.5 break-words text-sm font-medium text-brand-600 hover:underline dark:text-brand-400"
                >
                  Open the team folder in Google Drive <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
                </a>
              </div>
            ) : needsFolderLink ? (
              <form onSubmit={linkFolder} className="flex flex-wrap items-end gap-3">
                <div className="min-w-0 flex-1">
                  <Field label="Team Drive folder">
                    <Input
                      required
                      value={folderForm.drive_folder_url}
                      onChange={(e) => setFolderForm({ drive_folder_url: e.target.value })}
                      placeholder="https://drive.google.com/drive/folders/…"
                    />
                  </Field>
                </div>
                <Button type="submit" loading={linking}>
                  <Link2 className="h-4 w-4" aria-hidden /> Link folder
                </Button>
              </form>
            ) : null}

            <p className="text-xs text-stone-500">
              Everything the team stores — uploads, completed work, handover files and the app's data —
              lives in this folder{team.drive_folder_id ? "" : " once linked"}, and every member gets access automatically. Members never need a Google login.
            </p>
          </div>
        </Card>
      )}

      {/* Members */}
      <Card className="mb-6">
        <CardHeader
          title={`Members (${members.length})`}
          action={
            isAdmin && (
              <Button variant="secondary" onClick={() => { setLastInvite(null); setInviteOpen(true); }}>
                <Send className="h-4 w-4" aria-hidden /> Invite member
              </Button>
            )
          }
        />
        <div className="divide-y divide-stone-100 dark:divide-stone-800">
          {loading && members.length === 0 && <div className="p-5"><SkeletonList rows={2} /></div>}
          {members.map((member) => (
            <div key={member.user_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
              <div className="min-w-0">
                <p className="text-sm font-medium text-stone-900 dark:text-stone-100">
                  {member.name} {member.user_id === user?.user_id && <span className="text-xs text-stone-400">(you)</span>}
                </p>
                <p className="break-words text-xs text-stone-500">{member.email} · joined {formatDate(member.joined_at)}</p>
              </div>
              <div className="flex items-center gap-2">
                {isAdmin && member.role !== "owner" ? (
                  <Select value={member.role} onChange={(e) => void updateRole(member, e.target.value)} className="w-36" aria-label={`Role of ${member.name}`}>
                    {["admin", "coordinator", "member"].map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Badge value={member.role} />
                )}
                {isAdmin && member.role !== "owner" && (
                  <Button variant="ghost" className="p-2" onClick={() => setRemoveConfirm(member)} aria-label={`Remove ${member.name}`}>
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Invitations */}
      {useInvites && (
        <Card>
          <CardHeader
            title="Pending invitations"
            action={
              <Button variant="secondary" onClick={() => { setLastInvite(null); setInviteOpen(true); }}>
                <Link2 className="h-4 w-4" aria-hidden /> New invitation
              </Button>
            }
          />
          {lastInvite && lastInvite.invite_url && (
            <div className="mx-5 mt-4 flex flex-col gap-2 rounded-lg border border-brand-200 bg-brand-50 px-3.5 py-2.5 dark:border-brand-800 dark:bg-brand-950/60 sm:flex-row sm:items-center">
              <p className="min-w-0 flex-1 break-all text-sm text-brand-900 dark:text-brand-200">{lastInvite.invite_url}</p>
              <Button
                variant="secondary"
                className="w-full sm:w-auto"
                onClick={() => {
                  void navigator.clipboard.writeText(lastInvite.invite_url!);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                }}
              >
                {copied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
                {copied ? "Copied" : "Copy link"}
              </Button>
            </div>
          )}
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {(invitations ?? []).length === 0 && (
              <p className="px-5 py-6 text-sm text-stone-500">
                No invitations yet. Generate a link and share it with teammates.
              </p>
            )}
            {(invitations ?? []).map((invitation) => (
              <div key={invitation.invitation_id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
                <div className="min-w-0">
                  <p className="break-words text-sm text-stone-900 dark:text-stone-100">{invitation.email}</p>
                  <p className="text-xs text-stone-500">
                    {invitation.role} · expires {formatDate(invitation.expires_at)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge value={invitation.status} />
                  {invitation.status === "pending" && (
                    <Button variant="ghost" onClick={() => void revokeInvite(invitation)} aria-label="Revoke invitation">
                      Revoke
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Edit team modal */}
      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit team">
        <form onSubmit={saveTeamEdit} className="space-y-4">
          <Field label="Team name">
            <Input required value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
          </Field>
          <Field label="Description">
            <Textarea value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Save
            </Button>
          </div>
        </form>
      </Modal>

      {/* Link / change Drive folder modal */}
      <Modal open={folderOpen} onClose={() => setFolderOpen(false)} title={team.drive_folder_id ? "Change Drive folder" : "Link Drive folder"}>
        <form onSubmit={linkFolder} className="space-y-4">
          <Field label="Google Drive folder link">
            <Input
              required
              value={folderForm.drive_folder_url}
              onChange={(e) => setFolderForm({ drive_folder_url: e.target.value })}
              placeholder="https://drive.google.com/drive/folders/…"
            />
            <p className="mt-1.5 text-xs text-stone-500">
              Everything the team stores moves into this folder — existing data is migrated automatically
              and every member is granted access. Paste a link to the folder in your own Drive.
            </p>
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setFolderOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={linking}>
              <Link2 className="h-4 w-4" aria-hidden /> {team.drive_folder_id ? "Change folder" : "Link folder"}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Invite modal */}
      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite a member">
        <form onSubmit={sendInvite} className="space-y-4">
          <Field label="Email">
            <Input required type="email" value={inviteForm.email} onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })} placeholder="teammate@school.edu" />
          </Field>
          <Field label="Role">
            <Select value={inviteForm.role} onChange={(e) => setInviteForm({ ...inviteForm, role: e.target.value })}>
              {["member", "coordinator", "admin"].map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-xs text-stone-500">A single-use invite link valid for 7 days will be generated.</p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setInviteOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              <Send className="h-4 w-4" aria-hidden /> Create invite link
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!removeConfirm}
        onClose={() => setRemoveConfirm(null)}
        onConfirm={() => removeConfirm && void removeMember(removeConfirm)}
        title="Remove member"
        message={`Remove ${removeConfirm?.name ?? ""} from ${team.name}? They will lose access to this team's data.`}
        confirmLabel="Remove"
      />
    </div>
  );
}
