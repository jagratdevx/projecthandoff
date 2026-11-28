import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeftRight, FileDown, History, Send, Trash2, Upload } from "lucide-react";
import { api, downloadAttachment } from "../api/client";
import type { Activity, Attachment, Comment, Handover, Project, Subteam, Task, TaskStatus, TaskStatusRequest, User } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useMembers } from "../hooks/useMembers";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import {
  Avatar,
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
import { formatDate, timeAgo } from "../lib/format";

interface TaskDetailData {
  task: Task;
  comments: Comment[];
  attachments: Attachment[];
  handovers: Handover[];
  activity: Activity[];
  members: User[];
  names: Record<string, string>;
}

interface HandoverForm {
  subteam_id: string;
  proposed_owner_id: string;
  completed_work: string;
  remaining_work: string;
  current_state: string;
  blockers: string;
  next_actions: string;
  relevant_files: string;
  deadline: string;
  notes: string;
}

const EMPTY_HANDOVER: HandoverForm = {
  subteam_id: "",
  proposed_owner_id: "",
  completed_work: "",
  remaining_work: "",
  current_state: "",
  blockers: "",
  next_actions: "",
  relevant_files: "",
  deadline: "",
  notes: "",
};

export function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user, team } = useAuth();
  const members = useMembers();
  const toast = useToast();

  const { data, loading, error, reload } = useResource<TaskDetailData>(() => api(`/api/tasks/${id}`), [id], 15000);
  const { data: statusRequests, reload: reloadStatusRequests } = useResource<TaskStatusRequest[]>(
    () => (id ? api(`/api/tasks/${id}/status-requests`) : Promise.resolve([])),
    [id],
    15000,
  );
  const { data: projects } = useResource<Project[]>(() => api("/api/projects"), [], 60000);
  const { data: subteams } = useResource<Subteam[]>(
    () => (team ? api(`/api/teams/${team.team_id}/subteams`) : Promise.resolve([])),
    [team?.team_id],
    0,
  );

  const [comment, setComment] = useState("");
  const [posting, setPosting] = useState(false);
  const [statusValue, setStatusValue] = useState<TaskStatus | null>(null);
  const [descriptionDraft, setDescriptionDraft] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [handoverOpen, setHandoverOpen] = useState(false);
  const [handoverForm, setHandoverForm] = useState<HandoverForm>(EMPTY_HANDOVER);
  const [handoverError, setHandoverError] = useState<string | null>(null);
  const [savingHandover, setSavingHandover] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  if (loading && !data) return <SkeletonList rows={4} />;
  if (error || !data) return <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Task not found"}</p>;

  const { task, comments, attachments, handovers, activity, names } = data;
  const fullAccess = ["owner", "admin", "council", "teacher"].includes(user?.role ?? "");
  const mySubteamRole = user?.subteams?.find((s) => s.subteam_id === task.subteam_id)?.role;
  const canManageTask = fullAccess || mySubteamRole === "coordinator";
  const projectName = projects?.find((p) => p.project_id === task.project_id)?.name;
  const canDelete = user && (user.role === "owner" || user.role === "admin" || task.created_by === user.user_id);

  const patchTask = async (patch: Record<string, unknown>, successMessage: string) => {
    try {
      await api(`/api/tasks/${task.task_id}`, { method: "PATCH", body: patch });
      toast.push("success", successMessage);
      setStatusValue(null);
      setDescriptionDraft(null);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Update failed");
    }
  };

  const requestStatus = async (value: TaskStatus) => {
    try {
      await api(`/api/tasks/${task.task_id}/status-requests`, {
        method: "POST",
        body: { status: value },
      });
      toast.push("success", `Status change to ${value} sent for coordinator approval`);
      setStatusValue(null);
      void reloadStatusRequests();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not request status change");
    }
  };

  const reviewStatusRequest = async (requestId: string, action: "approve" | "reject") => {
    try {
      await api(`/api/tasks/status-requests/${requestId}/${action}`, { method: "POST" });
      toast.push("success", action === "approve" ? "Status change approved" : "Status change rejected");
      void reload();
      void reloadStatusRequests();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not review status change");
    }
  };

  const addComment = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!comment.trim()) return;
    setPosting(true);
    try {
      await api(`/api/tasks/${task.task_id}/comments`, { method: "POST", body: { comment: comment.trim() } });
      setComment("");
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not post comment");
    } finally {
      setPosting(false);
    }
  };

  const uploadFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("task_id", task.task_id);
      await api("/api/attachments", { form });
      toast.push("success", "File uploaded to Drive");
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const deleteAttachment = async (attachmentId: string) => {
    try {
      await api(`/api/attachments/${attachmentId}`, { method: "DELETE" });
      toast.push("success", "File deleted");
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Delete failed");
    }
  };

  const deleteTask = async () => {
    try {
      await api(`/api/tasks/${task.task_id}`, { method: "DELETE" });
      toast.push("success", "Task deleted");
      navigate("/tasks");
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Delete failed");
    }
  };

  const createHandover = async (event: React.FormEvent) => {
    event.preventDefault();
    setSavingHandover(true);
    setHandoverError(null);
    try {
      await api("/api/handovers", {
        method: "POST",
        body: { ...handoverForm, task_id: task.task_id, subteam_id: handoverForm.subteam_id },
      });
      toast.push("success", "Handover request sent");
      setHandoverOpen(false);
      setHandoverForm(EMPTY_HANDOVER);
      void reload();
    } catch (err) {
      setHandoverError(err instanceof Error ? err.message : "Failed to create handover");
    } finally {
      setSavingHandover(false);
    }
  };

  const hasOpenHandover = handovers.some((h) => h.status === "pending" || h.status === "clarification_requested");
  const isAssignee = task.assigned_to === user?.user_id;

  return (
    <div>
      <button onClick={() => navigate("/tasks")} className="mb-3 text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-100">
        ← Back to tasks
      </button>

      <PageHeader
        title={task.title}
        subtitle={projectName ? `Project: ${projectName}` : "No project"}
        actions={
          <>
            <Badge value={task.status} />
            <Badge value={task.priority} />
            {task.project_id && (
              <Link to={`/projects/${task.project_id}`}>
                <Button variant="secondary">Open project</Button>
              </Link>
            )}
            {(isAssignee || user?.role === "owner" || user?.role === "admin") && !hasOpenHandover && (
              <Button
                onClick={() => {
                  setHandoverForm({ ...EMPTY_HANDOVER, deadline: task.deadline });
                  setHandoverOpen(true);
                }}
              >
                <ArrowLeftRight className="h-4 w-4" aria-hidden /> Hand over
              </Button>
            )}
            {canDelete && (
              <Button variant="ghost" onClick={() => setDeleteOpen(true)} aria-label="Delete task">
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            )}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main column */}
        <div className="space-y-6 lg:col-span-2">
          {/* Properties */}
          <Card className="p-5">
            <div className="grid gap-4 sm:grid-cols-4">
              <Field label="Status">
                <Select
                  value={statusValue ?? task.status}
                  onChange={(e) => {
                    const value = e.target.value as TaskStatus;
                    setStatusValue(value);
                    if (canManageTask) void patchTask({ status: value }, `Status set to ${value}`);
                    else void requestStatus(value);
                  }}
                >
                  {["Not Started", "In Progress", "Blocked", "Under Review", "Completed"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Priority">
                <Select
                  defaultValue={task.priority}
                  disabled={!canManageTask}
                  onChange={(e) => void patchTask({ priority: e.target.value }, "Priority updated")}
                >
                  {["Low", "Medium", "High", "Critical"].map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Assignee">
                <Select
                  defaultValue={task.assigned_to}
                  disabled={!canManageTask}
                  onChange={(e) => void patchTask({ assigned_to: e.target.value || undefined }, "Assignee updated")}
                >
                  <option value="">Unassigned</option>
                  {members.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Deadline">
                <Input
                  type="date"
                  defaultValue={task.deadline}
                  disabled={!canManageTask}
                  onChange={(e) => void patchTask({ deadline: e.target.value }, "Deadline updated")}
                />
              </Field>
            </div>
            <div className="mt-4 border-t border-stone-100 pt-4 dark:border-stone-800">
              <Field label="Description">
                {descriptionDraft === null ? (
                  <button
                    disabled={!canManageTask}
                    onClick={() => setDescriptionDraft(task.description)}
                    className="w-full rounded-lg border border-dashed border-stone-300 px-3 py-2.5 text-left text-sm text-stone-600 transition hover:border-brand-400 disabled:cursor-not-allowed disabled:opacity-60 dark:border-stone-700 dark:text-stone-300"
                  >
                    {task.description || "Click to add a description…"}
                  </button>
                ) : (
                  <div className="space-y-2">
                    <Textarea
                      autoFocus
                      rows={4}
                      value={descriptionDraft}
                      onChange={(e) => setDescriptionDraft(e.target.value)}
                    />
                    <div className="flex justify-end gap-2">
                      <Button variant="secondary" onClick={() => setDescriptionDraft(null)}>
                        Cancel
                      </Button>
                      <Button
                        onClick={() =>
                          void patchTask({ description: descriptionDraft }, "Description updated")
                        }
                      >
                        Save
                      </Button>
                    </div>
                  </div>
                )}
              </Field>
              <p className="mt-3 text-xs text-stone-400">
                Created {formatDate(task.created_at)} · version {task.version} · updated {timeAgo(task.updated_at)}
              </p>
            </div>
          </Card>

          {!!statusRequests?.length && (
            <Card>
              <CardHeader title={`Status change requests (${statusRequests.filter((r) => r.status === "pending").length})`} />
              <div className="divide-y divide-stone-100 dark:divide-stone-800">
                {statusRequests.map((request) => (
                  <div key={request.request_id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <p className="text-sm text-stone-800 dark:text-stone-200">
                        {request.requested_by_name || "A member"} → <Badge value={request.requested_status} />
                      </p>
                      <p className="text-xs text-stone-500">
                        {request.note || "No note"} · {timeAgo(request.created_at)} · {request.status}
                      </p>
                    </div>
                    {canManageTask && request.status === "pending" && (
                      <div className="flex gap-2">
                        <Button onClick={() => void reviewStatusRequest(request.request_id, "approve")}>Approve</Button>
                        <Button variant="secondary" onClick={() => void reviewStatusRequest(request.request_id, "reject")}>
                          Reject
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Handovers */}
          <Card>
            <CardHeader title={`Handover history (${handovers.length})`} />
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {handovers.length === 0 && (
                <p className="px-5 py-5 text-sm text-stone-500">
                  No handovers for this task yet. Use “Hand over” to transfer responsibility with full context.
                </p>
              )}
              {handovers.map((handover) => (
                <Link key={handover.handover_id} to={`/handovers/${handover.handover_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50 dark:hover:bg-stone-800/60">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm text-stone-700 dark:text-stone-300">
                      {names[handover.previous_owner_id] ?? "Unknown"} → {names[handover.proposed_owner_id] ?? "Unknown"}
                    </p>
                    <Badge value={handover.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-stone-400">sent {timeAgo(handover.created_at)}</p>
                </Link>
              ))}
            </div>
          </Card>

          {/* Comments */}
          <Card>
            <CardHeader title={`Discussion (${comments.length})`} />
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {comments.length === 0 && <p className="px-5 py-5 text-sm text-stone-500">No comments yet.</p>}
              {comments.map((entry) => (
                <div key={entry.comment_id} className="flex gap-3 px-5 py-3.5">
                  <Avatar name={names[entry.user_id] ?? "Unknown"} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">
                      <span className="font-medium text-stone-900 dark:text-stone-100">{names[entry.user_id] ?? "Unknown"}</span>{" "}
                      <span className="text-xs text-stone-400">{timeAgo(entry.created_at)}</span>
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-stone-700 dark:text-stone-300">{entry.comment}</p>
                  </div>
                </div>
              ))}
            </div>
            <form onSubmit={addComment} className="flex items-start gap-2 border-t border-stone-200 p-4 dark:border-stone-800">
              <Textarea
                rows={2}
                placeholder="Write a comment…"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                aria-label="Write a comment"
              />
              <Button type="submit" loading={posting} disabled={!comment.trim()} aria-label="Post comment">
                <Send className="h-4 w-4" aria-hidden />
              </Button>
            </form>
          </Card>
        </div>

        {/* Side column */}
        <div className="space-y-6">
          {/* Attachments */}
          <Card>
            <CardHeader
              title="Files"
              action={
                <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">
                  <Upload className="h-3.5 w-3.5" aria-hidden />
                  {uploading ? "Uploading…" : "Attach"}
                  <input ref={fileInput} type="file" className="hidden" onChange={uploadFile} disabled={uploading} />
                </label>
              }
            />
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {attachments.length === 0 && <p className="px-5 py-4 text-sm text-stone-500">No files attached.</p>}
              {attachments.map((file) => (
                <div key={file.attachment_id} className="flex items-center justify-between gap-2 px-4 py-2.5">
                  <button
                    onClick={() => void downloadAttachment(file.attachment_id, file.file_name).catch((e) => toast.push("error", e instanceof Error ? e.message : "Download failed"))}
                    className="flex min-w-0 items-center gap-2 text-left"
                    title="Download file"
                  >
                    <FileDown className="h-4 w-4 shrink-0 text-stone-400" aria-hidden />
                    <span className="truncate text-sm text-stone-700 hover:underline dark:text-stone-300">{file.file_name}</span>
                  </button>
                  <Button
                    variant="ghost"
                    className="p-1"
                    onClick={() => void deleteAttachment(file.attachment_id)}
                    aria-label={`Delete ${file.file_name}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                </div>
              ))}
            </div>
          </Card>

          {/* History */}
          <Card>
            <CardHeader title="History" />
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {activity.length === 0 && (
                <div className="flex items-center gap-2 px-5 py-4 text-sm text-stone-500">
                  <History className="h-4 w-4" aria-hidden /> No history yet.
                </div>
              )}
              {activity.map((entry) => (
                <div key={entry.activity_id} className="px-5 py-2.5">
                  <p className="text-xs text-stone-700 dark:text-stone-300">{entry.description}</p>
                  <p className="mt-0.5 text-[11px] text-stone-400">{timeAgo(entry.timestamp)}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Handover modal */}
      <Modal open={handoverOpen} onClose={() => setHandoverOpen(false)} title="Hand over this task" wide>
        <p className="mb-4 text-sm text-stone-500 dark:text-stone-400">
          The new owner receives the complete context: what is done, what remains, current state, blockers and next
          actions. They can accept, reject with a reason, or ask for clarification.
        </p>
        <form onSubmit={createHandover} className="space-y-4">
          {handoverError && <p className="text-sm text-red-600 dark:text-red-400">{handoverError}</p>}
          <Field label="Subteam" hint="Optional — leave blank to use the task's subteam.">
            <Select
              value={handoverForm.subteam_id}
              onChange={(e) => setHandoverForm({ ...handoverForm, subteam_id: e.target.value })}
            >
              <option value="">Main team</option>
              {(subteams ?? []).map((subteam) => (
                <option key={subteam.subteam_id} value={subteam.subteam_id}>
                  {subteam.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Proposed new owner">
            <Select required value={handoverForm.proposed_owner_id} onChange={(e) => setHandoverForm({ ...handoverForm, proposed_owner_id: e.target.value })}>
              <option value="">Select a team member…</option>
              {members
                .filter((m) => m.user_id !== task.assigned_to)
                .map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.name}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Work already completed *">
            <Textarea required value={handoverForm.completed_work} onChange={(e) => setHandoverForm({ ...handoverForm, completed_work: e.target.value })} placeholder="Chassis assembled, motors mounted, tested at low speed…" />
          </Field>
          <Field label="Work remaining">
            <Textarea value={handoverForm.remaining_work} onChange={(e) => setHandoverForm({ ...handoverForm, remaining_work: e.target.value })} placeholder="Wiring, firmware, test run…" />
          </Field>
          <Field label="Current state of the work">
            <Textarea value={handoverForm.current_state} onChange={(e) => setHandoverForm({ ...handoverForm, current_state: e.target.value })} placeholder="Robot powers on but the left drive cuts out…" />
          </Field>
          <Field label="Existing blockers">
            <Textarea value={handoverForm.blockers} onChange={(e) => setHandoverForm({ ...handoverForm, blockers: e.target.value })} placeholder="Waiting on the replacement motor controller…" />
          </Field>
          <Field label="Next recommended actions">
            <Textarea value={handoverForm.next_actions} onChange={(e) => setHandoverForm({ ...handoverForm, next_actions: e.target.value })} placeholder="1. Swap controller 2. Re-run diagnostics…" />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Relevant files" hint="File names or links, comma separated.">
              <Input value={handoverForm.relevant_files} onChange={(e) => setHandoverForm({ ...handoverForm, relevant_files: e.target.value })} placeholder="wiring-diagram.pdf" />
            </Field>
            <Field label="Deadline">
              <Input type="date" value={handoverForm.deadline} onChange={(e) => setHandoverForm({ ...handoverForm, deadline: e.target.value })} />
            </Field>
          </div>
          <Field label="Additional notes" hint="Added as a comment on the task.">
            <Textarea value={handoverForm.notes} onChange={(e) => setHandoverForm({ ...handoverForm, notes: e.target.value })} placeholder="Anything else the new owner should know…" />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setHandoverOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={savingHandover}>
              <ArrowLeftRight className="h-4 w-4" aria-hidden /> Send handover
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={deleteTask}
        title="Delete task"
        message={`Delete “${task.title}”? This removes the task and its handover history from the board.`}
        confirmLabel="Delete task"
      />
    </div>
  );
}
