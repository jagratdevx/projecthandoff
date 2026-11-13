import { useState } from "react";
import { Check, Copy, Link2, Send, Trash2, UserPlus } from "lucide-react";
import { api } from "../api/client";
import type { Invitation, Team, User } from "../api/types";
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

  const [teamForm, setTeamForm] = useState({ name: "", description: "" });
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState({ name: "", description: "" });
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({ email: "", role: "member" });
  const [lastInvite, setLastInvite] = useState<Invitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState<User | null>(null);
  const [saving, setSaving] = useState(false);

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
                  await api("/api/teams", { method: "POST", body: teamForm });
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
              <Button type="submit" loading={saving} className="w-full">
                <UserPlus className="h-4 w-4" aria-hidden /> Create team
              </Button>
              <p className="text-center text-xs text-zinc-500">Have an invite link instead? Open it and register there.</p>
            </form>
          </Card>
        )}
      </div>
    );
  }

  const members = data?.members ?? [];

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
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {loading && members.length === 0 && <div className="p-5"><SkeletonList rows={2} /></div>}
          {members.map((member) => (
            <div key={member.user_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
              <div className="min-w-0">
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {member.name} {member.user_id === user?.user_id && <span className="text-xs text-zinc-400">(you)</span>}
                </p>
                <p className="truncate text-xs text-zinc-500">{member.email} · joined {formatDate(member.joined_at)}</p>
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
                  <Button variant="ghost" className="p-1" onClick={() => setRemoveConfirm(member)} aria-label={`Remove ${member.name}`}>
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
            <div className="mx-5 mt-4 flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3.5 py-2.5 dark:border-indigo-800 dark:bg-indigo-950/60">
              <p className="flex-1 truncate text-sm text-indigo-900 dark:text-indigo-200">{lastInvite.invite_url}</p>
              <Button
                variant="secondary"
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
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {(invitations ?? []).length === 0 && (
              <p className="px-5 py-6 text-sm text-zinc-500">
                No invitations yet. Generate a link and share it with teammates.
              </p>
            )}
            {(invitations ?? []).map((invitation) => (
              <div key={invitation.invitation_id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm text-zinc-900 dark:text-zinc-100">{invitation.email}</p>
                  <p className="text-xs text-zinc-500">
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
          <p className="text-xs text-zinc-500">A single-use invite link valid for 7 days will be generated.</p>
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
