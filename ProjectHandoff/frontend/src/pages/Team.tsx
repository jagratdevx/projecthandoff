import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Archive, Check, Copy, ExternalLink, FolderOpen, Link2, RefreshCw, Send, Share2, Trash2, UserPlus, Users } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Invitation, Subteam, SubteamMember, SubteamRole, Team, TeamDriveStatus, User } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useReadOnly } from "../hooks/useReadOnly";
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
  Tabs,
  Textarea,
} from "../components/ui";
import { formatDate } from "../lib/format";

type TeamTab = "members" | "subteams" | "invitations";

const DRIVE_SETUP_HELP =
  "One-time, free (~10 minutes): console.cloud.google.com → create a project → enable the Google Drive API → OAuth consent screen (External, add yourself as test user) → Credentials → OAuth client ID → Web application. Paste the redirect URI below as an Authorized redirect URI, then copy the client ID and secret here.";

export function TeamPage() {
  const { user, refresh, canCreateTeam, completeTeam } = useAuth();
  const toast = useToast();
  const readOnly = useReadOnly();

  const { data, loading, reload } = useResource<{ team: Team | null; members: User[] }>(
    () => api("/api/teams/mine"),
    [],
    20000,
  );

  const team = data?.team ?? null;
  const isAdmin = ["owner", "admin", "council", "teacher"].includes(user?.role ?? "");
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

  const { data: subteams, loading: subteamsLoading, reload: reloadSubteams } = useResource<Subteam[]>(
    () => (team ? api(`/api/teams/${team.team_id}/subteams`) : Promise.resolve([])),
    [team?.team_id],
    0,
  );

  const [teamTab, setTeamTab] = useState<TeamTab>("members");
  const [subteamOpen, setSubteamOpen] = useState(false);
  const [subteamForm, setSubteamForm] = useState({ name: "", description: "" });
  const [subteamError, setSubteamError] = useState("");
  const [subteamSaving, setSubteamSaving] = useState(false);
  const [subteamToDelete, setSubteamToDelete] = useState<Subteam | null>(null);
  const [deletingSubteam, setDeletingSubteam] = useState(false);
  const [manageFor, setManageFor] = useState<Subteam | null>(null);
  const [addMemberForm, setAddMemberForm] = useState<{ user_id: string; role: SubteamRole }>({ user_id: "", role: "volunteer" });
  const [subteamMemberToRemove, setSubteamMemberToRemove] = useState<SubteamMember | null>(null);
  const [subteamMemberBusy, setSubteamMemberBusy] = useState(false);
  const [subteamInviteFor, setSubteamInviteFor] = useState<Subteam | null>(null);
  const [subteamInviteForm, setSubteamInviteForm] = useState<{ email: string; role: SubteamRole }>({ email: "", role: "volunteer" });
  const [subteamInvite, setSubteamInvite] = useState<Invitation | null>(null);
  const [subteamInviteSaving, setSubteamInviteSaving] = useState(false);
  const [subteamInviteError, setSubteamInviteError] = useState("");
  const [subteamInviteCopied, setSubteamInviteCopied] = useState(false);

  const { data: managedMembers, loading: managedMembersLoading, reload: reloadManagedMembers } = useResource<SubteamMember[]>(
    () => (manageFor ? api(`/api/teams/${team?.team_id ?? ""}/subteams/${manageFor.subteam_id}/members`) : Promise.resolve([])),
    [manageFor?.subteam_id],
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
  const [completeOpen, setCompleteOpen] = useState(false);
  const [forceOpen, setForceOpen] = useState(false);
  const [completing, setCompleting] = useState(false);

  const createSubteam = async (event: FormEvent) => {
    event.preventDefault();
    if (!team) return;
    setSubteamSaving(true);
    setSubteamError("");
    try {
      await api(`/api/teams/${team.team_id}/subteams`, {
        method: "POST",
        body: { name: subteamForm.name.trim(), description: subteamForm.description.trim() },
      });
      toast.push("success", "Subteam created with its own Drive folder");
      setSubteamForm({ name: "", description: "" });
      setSubteamOpen(false);
      setTeamTab("subteams");
      void reloadSubteams();
    } catch (err) {
      setSubteamError(err instanceof Error ? err.message : "Could not create subteam");
    } finally {
      setSubteamSaving(false);
    }
  };

  const deleteSubteam = async () => {
    if (!team || !subteamToDelete) return;
    setDeletingSubteam(true);
    try {
      await api(`/api/teams/${team.team_id}/subteams/${subteamToDelete.subteam_id}`, { method: "DELETE" });
      toast.push("success", "Subteam removed — its Drive folder was kept");
      setSubteamToDelete(null);
      void reloadSubteams();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not remove subteam");
    } finally {
      setDeletingSubteam(false);
    }
  };

  const refreshSubteamData = () => {
    void reloadSubteams();
    void reloadManagedMembers();
    void refresh();
  };

  const addSubteamMember = async (event: FormEvent) => {
    event.preventDefault();
    if (!team || !manageFor || !addMemberForm.user_id) return;
    setSubteamMemberBusy(true);
    try {
      await api(`/api/teams/${team.team_id}/subteams/${manageFor.subteam_id}/members`, {
        method: "POST",
        body: addMemberForm,
      });
      toast.push("success", `Added to ${manageFor.name} as ${addMemberForm.role}`);
      setAddMemberForm({ user_id: "", role: "volunteer" });
      refreshSubteamData();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not add member");
    } finally {
      setSubteamMemberBusy(false);
    }
  };

  const changeSubteamMemberRole = async (member: SubteamMember, role: SubteamRole) => {
    if (!team || !manageFor) return;
    try {
      await api(`/api/teams/${team.team_id}/subteams/${manageFor.subteam_id}/members/${member.user_id}`, {
        method: "PATCH",
        body: { role },
      });
      toast.push("success", `${member.name || "Member"} is now ${role} in ${manageFor.name}`);
      refreshSubteamData();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Role update failed");
    }
  };

  const removeSubteamMember = async () => {
    if (!team || !manageFor || !subteamMemberToRemove) return;
    setSubteamMemberBusy(true);
    try {
      await api(`/api/teams/${team.team_id}/subteams/${manageFor.subteam_id}/members/${subteamMemberToRemove.user_id}`, {
        method: "DELETE",
      });
      toast.push("success", `${subteamMemberToRemove.name || "Member"} removed from ${manageFor.name}`);
      setSubteamMemberToRemove(null);
      refreshSubteamData();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Removal failed");
    } finally {
      setSubteamMemberBusy(false);
    }
  };

  const sendSubteamInvite = async (event: FormEvent) => {
    event.preventDefault();
    if (!team || !subteamInviteFor) return;
    setSubteamInviteSaving(true);
    setSubteamInviteError("");
    try {
      const invitation = await api<Invitation>(
        `/api/teams/${team.team_id}/subteams/${subteamInviteFor.subteam_id}/invitations`,
        { method: "POST", body: subteamInviteForm },
      );
      setSubteamInvite(invitation);
      toast.push("success", "Subteam invitation created — share the link");
      setSubteamInviteForm({ email: "", role: "volunteer" });
      void reloadInvites();
    } catch (err) {
      setSubteamInviteError(err instanceof Error ? err.message : "Could not create invitation");
    } finally {
      setSubteamInviteSaving(false);
    }
  };

  // ------------------------------------------------------------------ create team
  const createEvent = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      const created = await api<Team & { authorize_url?: string; next_step?: string }>("/api/teams", {
        method: "POST",
        body: teamForm,
      });
      if (created.authorize_url) {
        // One-time Google consent for the team owner — members never see this.
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
  };

  const renderCreateForm = (title: string, subtitle: string) => (
    <div>
      <PageHeader title={title} subtitle={subtitle} />
      {loading ? (
        <SkeletonList rows={2} />
      ) : (
        <Card className="mx-auto max-w-md p-6">
          <form onSubmit={(event) => void createEvent(event)} className="space-y-4">
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

  const completeEvent = async (force = false) => {
    if (!team) return;
    setCompleting(true);
    try {
      await completeTeam(team.team_id, force);
      toast.push("success", "Event completed — its history is preserved in memories");
      setCompleteOpen(false);
      setForceOpen(false);
      void reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 502 && !force) {
        setCompleteOpen(false);
        setForceOpen(true);
      } else {
        toast.push("error", err instanceof Error ? err.message : "Could not complete the event");
      }
    } finally {
      setCompleting(false);
    }
  };

  if (!team) {
    return renderCreateForm("Team", "Create a team to unlock projects, tasks and handovers");
  }

  // Completed events are archived and read-only. Offer a fresh event instead.
  if (readOnly) {
    return (
      <div>
        <div className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
          <Archive className="h-4 w-4 shrink-0" aria-hidden />
          <p className="min-w-0 flex-1">
            <strong className="font-semibold">{team.name}</strong> is complete and archived. This team is read-only —
            its history remains available in memories.
          </p>
          <Link to="/memories" className="font-medium underline underline-offset-2 hover:no-underline">
            Browse memories
          </Link>
        </div>
        {canCreateTeam ? (
          renderCreateForm("Start a new event", "Create a new team to keep working — your archived event stays safe.")
        ) : (
          <Card className="mx-auto max-w-md p-6 text-sm text-stone-600 dark:text-stone-300">
            You cannot create another team while you belong to an active one. Switch teams from the sidebar, or browse your memories.
          </Card>
        )}
      </div>
    );
  }

  const canComplete = user?.role === "owner" || user?.role === "teacher";
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
          <>
            {canComplete && (
              <Button variant="secondary" onClick={() => setCompleteOpen(true)}>
                Complete event
              </Button>
            )}
            {isAdmin && (
              <Button
                variant="secondary"
                onClick={() => {
                  setEditForm({ name: team.name, description: team.description });
                  setEditOpen(true);
                }}
              >
                Edit team
              </Button>
            )}
          </>
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

      <div className="mb-4">
        <Tabs<TeamTab>
          tabs={[
            { id: "members", label: "Members", count: members.length },
            { id: "subteams", label: "Subteams", count: subteams?.length ?? 0 },
            ...(useInvites ? [{ id: "invitations" as const, label: "Invitations", count: invitations?.length ?? 0 }] : []),
          ]}
          value={teamTab}
          onChange={setTeamTab}
        />
      </div>

      {teamTab === "members" && (
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
                    {["admin", "council", "teacher", "coordinator", "member"].map((role) => (
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
      )}

      {teamTab === "subteams" && (
        <Card className="mb-6">
          <CardHeader
            title="Subteams"
            action={
              isAdmin && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSubteamForm({ name: "", description: "" });
                    setSubteamError("");
                    setSubteamOpen(true);
                  }}
                >
                  New subteam
                </Button>
              )
            }
          />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {subteamsLoading && !subteams?.length && <div className="p-5"><SkeletonList rows={2} /></div>}
            {subteams?.map((subteam) => {
              const canManage = !!subteam.can_manage || isAdmin;
              return (
              <div key={subteam.subteam_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-stone-900 dark:text-stone-100">{subteam.name}</p>
                  <p className="break-words text-xs text-stone-500">{subteam.description || "No description"}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    {subteam.my_role ? (
                      <Badge value={subteam.my_role} />
                    ) : (
                      <span className="text-xs text-stone-400">Not a member</span>
                    )}
                    <span className="text-xs text-stone-500">
                      {subteam.member_count ?? 0} {subteam.member_count === 1 ? "member" : "members"}
                    </span>
                    <Link
                      to={`/team/subteams/${encodeURIComponent(subteam.subteam_id)}/projects`}
                      className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                    >
                      Projects
                    </Link>
                    <Link
                      to={`/activity?subteam_id=${encodeURIComponent(subteam.subteam_id)}`}
                      className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                    >
                      View log
                    </Link>
                  </div>
                  {subteam.folder_url ? (
                    <a
                      href={subteam.folder_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 inline-flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
                    >
                      Open folder in Google Drive <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  ) : (
                    <p className="mt-1 break-words text-xs text-stone-400">Folder: {subteam.folder_id || "pending"}</p>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  {canManage && (
                    <>
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setSubteamInviteFor(subteam);
                          setSubteamInvite(null);
                          setSubteamInviteError("");
                          setSubteamInviteCopied(false);
                          setSubteamInviteForm({ email: "", role: "volunteer" });
                        }}
                      >
                        <UserPlus className="h-4 w-4" aria-hidden /> Invite
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setManageFor(subteam);
                          setAddMemberForm({ user_id: "", role: "volunteer" });
                        }}
                      >
                        <Users className="h-4 w-4" aria-hidden /> Manage
                      </Button>
                    </>
                  )}
                  {isAdmin && (
                    <Button
                      variant="ghost"
                      className="p-2"
                      onClick={() => setSubteamToDelete(subteam)}
                      aria-label={`Remove ${subteam.name}`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  )}
                </div>
              </div>
              );
            })}
            {!subteamsLoading && !subteams?.length && (
              <p className="px-5 py-4 text-sm text-stone-500">
                No subteams yet. Create one to give each group a readable folder in Drive.
              </p>
            )}
          </div>
        </Card>
      )}

      {teamTab === "invitations" && useInvites && (
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

      {/* Create subteam modal */}
      <Modal open={subteamOpen} onClose={() => setSubteamOpen(false)} title="New subteam">
        <form onSubmit={(event) => void createSubteam(event)} className="space-y-4">
          <Field
            label="Subteam name"
            hint="A Drive folder with this name is created inside the team folder. Names must be unique and cannot match the team name."
          >
            <Input
              required
              maxLength={80}
              value={subteamForm.name}
              onChange={(e) => setSubteamForm({ ...subteamForm, name: e.target.value })}
              placeholder="Design"
            />
          </Field>
          <Field label="Description">
            <Textarea
              value={subteamForm.description}
              onChange={(e) => setSubteamForm({ ...subteamForm, description: e.target.value })}
              placeholder="What this group handles"
            />
          </Field>
          {subteamError && <p className="text-sm text-red-600 dark:text-red-400">{subteamError}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setSubteamOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={subteamSaving}>
              Create subteam
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!subteamToDelete}
        onClose={() => setSubteamToDelete(null)}
        onConfirm={() => void deleteSubteam()}
        title="Remove subteam"
        message={`Remove “${subteamToDelete?.name ?? ""}” from the team? Its Drive folder is kept so no files are lost.`}
        confirmLabel="Remove"
        loading={deletingSubteam}
      />

      {/* Manage subteam members */}
      <Modal open={!!manageFor} onClose={() => setManageFor(null)} title={`Manage ${manageFor?.name ?? "subteam"}`} wide>
        {manageFor?.can_manage || isAdmin ? (
          <>
            <p className="mb-4 text-sm text-stone-500 dark:text-stone-400">
              Add existing team members, change their subteam role, or remove them. The last coordinator cannot be
              removed or demoted.
            </p>
            <form onSubmit={addSubteamMember} className="mb-4 flex flex-wrap items-end gap-2 rounded-xl bg-stone-50 p-3 dark:bg-stone-900/60">
              <div className="min-w-[12rem] flex-1">
                <Field label="Add team member">
                  <Select
                    required
                    value={addMemberForm.user_id}
                    onChange={(e) => setAddMemberForm({ ...addMemberForm, user_id: e.target.value })}
                  >
                    <option value="">Choose a member…</option>
                    {members
                      .filter((member) => !managedMembers?.some((m) => m.user_id === member.user_id))
                      .map((member) => (
                        <option key={member.user_id} value={member.user_id}>
                          {member.name}
                        </option>
                      ))}
                  </Select>
                </Field>
              </div>
              <div className="w-32">
                <Field label="Role">
                  <Select
                    value={addMemberForm.role}
                    onChange={(e) => setAddMemberForm({ ...addMemberForm, role: e.target.value as SubteamRole })}
                  >
                    <option value="coordinator">coordinator</option>
                    <option value="volunteer">volunteer</option>
                  </Select>
                </Field>
              </div>
              <Button type="submit" loading={subteamMemberBusy} disabled={!addMemberForm.user_id}>
                Add
              </Button>
            </form>
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {managedMembersLoading && !managedMembers?.length && <div className="p-4"><SkeletonList rows={2} /></div>}
              {managedMembers?.map((member) => (
                <div key={member.user_id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-stone-900 dark:text-stone-100">{member.name || member.user_id}</p>
                    <p className="break-words text-xs text-stone-500">{member.email}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={member.role}
                      onChange={(e) => void changeSubteamMemberRole(member, e.target.value as SubteamRole)}
                      className="w-32"
                      aria-label={`Subteam role of ${member.name || member.user_id}`}
                    >
                      <option value="coordinator">coordinator</option>
                      <option value="volunteer">volunteer</option>
                    </Select>
                    <Button
                      variant="ghost"
                      className="p-2"
                      onClick={() => setSubteamMemberToRemove(member)}
                      aria-label={`Remove ${member.name || member.user_id} from subteam`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  </div>
                </div>
              ))}
              {!managedMembersLoading && !managedMembers?.length && (
                <p className="py-4 text-sm text-stone-500">No members in this subteam yet.</p>
              )}
            </div>
          </>
        ) : (
          <p className="text-sm text-stone-500">You cannot manage this subteam.</p>
        )}
      </Modal>

      <ConfirmDialog
        open={!!subteamMemberToRemove}
        onClose={() => setSubteamMemberToRemove(null)}
        onConfirm={() => void removeSubteamMember()}
        title="Remove subteam member"
        message={`Remove ${subteamMemberToRemove?.name || "this member"} from ${manageFor?.name ?? "this subteam"}? They stay on the main team.`}
        confirmLabel="Remove"
        loading={subteamMemberBusy}
      />

      {/* Invite someone new into a subteam with a role */}
      <Modal open={!!subteamInviteFor} onClose={() => setSubteamInviteFor(null)} title={`Invite to ${subteamInviteFor?.name ?? "subteam"}`}>
        <form onSubmit={sendSubteamInvite} className="space-y-4">
          <Field label="Email">
            <Input
              required
              type="email"
              value={subteamInviteForm.email}
              onChange={(e) => setSubteamInviteForm({ ...subteamInviteForm, email: e.target.value })}
              placeholder="teammate@school.edu"
            />
          </Field>
          <Field label="Subteam role" hint="They join the main team as a member with this role in the subteam.">
            <Select
              value={subteamInviteForm.role}
              onChange={(e) => setSubteamInviteForm({ ...subteamInviteForm, role: e.target.value as SubteamRole })}
            >
              <option value="volunteer">volunteer</option>
              <option value="coordinator">coordinator</option>
            </Select>
          </Field>
          {subteamInviteError && <p className="text-sm text-red-600 dark:text-red-400">{subteamInviteError}</p>}
          {subteamInvite?.invite_url && (
            <div className="flex flex-col gap-2 rounded-lg border border-brand-200 bg-brand-50 px-3.5 py-2.5 dark:border-brand-800 dark:bg-brand-950/60 sm:flex-row sm:items-center">
              <p className="min-w-0 flex-1 break-all text-sm text-brand-900 dark:text-brand-200">{subteamInvite.invite_url}</p>
              <Button
                variant="secondary"
                className="w-full sm:w-auto"
                onClick={() => {
                  void navigator.clipboard.writeText(subteamInvite.invite_url!);
                  setSubteamInviteCopied(true);
                  window.setTimeout(() => setSubteamInviteCopied(false), 2000);
                }}
              >
                {subteamInviteCopied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
                {subteamInviteCopied ? "Copied" : "Copy link"}
              </Button>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setSubteamInviteFor(null)}>
              Close
            </Button>
            <Button type="submit" loading={subteamInviteSaving}>
              <Send className="h-4 w-4" aria-hidden /> Create invite link
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
              {["member", "coordinator", "council", "teacher", "admin"].map((role) => (
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

      <ConfirmDialog
        open={completeOpen}
        onClose={() => setCompleteOpen(false)}
        onConfirm={() => void completeEvent()}
        title="Complete this event?"
        message={`“${team.name}” will be archived and become read-only for every member. Its history will stay available in memories, and all pending invitations will expire. This cannot be undone.`}
        confirmLabel="Complete event"
        loading={completing}
      />

      <ConfirmDialog
        open={forceOpen}
        onClose={() => setForceOpen(false)}
        onConfirm={() => void completeEvent(true)}
        title="Complete without Drive access?"
        message="Some members' folders could not be switched to read-only. Completing anyway archives the event now, but those Drive permissions may remain unchanged."
        confirmLabel="Complete anyway"
        loading={completing}
      />
    </div>
  );
}
