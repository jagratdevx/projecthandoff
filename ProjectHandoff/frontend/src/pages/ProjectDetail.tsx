import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Archive, ClipboardList, FileDown, History, Plus, Upload } from "lucide-react";
import { api, downloadAttachment } from "../api/client";
import type { Activity, Attachment, Project, Task, User } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useMembers } from "../hooks/useMembers";
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
  ProgressBar,
  Select,
  SkeletonList,
  Tabs,
  Textarea,
} from "../components/ui";
import { formatDate, timeAgo } from "../lib/format";

interface ProjectDetailData {
  project: Project;
  tasks: Task[];
  progress: { total: number; completed: number };
  activity: Activity[];
  members: User[];
}

interface TabId {
  id: "tasks" | "activity" | "files";
}

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const members = useMembers();
  const toast = useToast();

  const { data, loading, error, reload } = useResource<ProjectDetailData>(
    () => api(`/api/projects/${id}`),
    [id],
    15000,
  );
  const { data: files, reload: reloadFiles } = useResource<Attachment[]>(
    () => api(`/api/attachments?project_id=${id}`),
    [id],
    30000,
  );

  const [tab, setTab] = useState<TabId["id"]>("tasks");
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [editForm, setEditForm] = useState({ name: "", description: "", deadline: "", priority: "Medium", status: "Active", owner_id: "" });
  const [taskForm, setTaskForm] = useState({ title: "", description: "", assigned_to: "", deadline: "", priority: "Medium", status: "Not Started" });
  const [saving, setSaving] = useState(false);

  const canManage = useMemo(() => {
    if (!data || !user) return false;
    return user.role === "owner" || user.role === "admin" || data.project.owner_id === user.user_id;
  }, [data, user]);

  if (loading && !data) return <SkeletonList rows={4} />;
  if (error || !data) return <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Project not found"}</p>;

  const { project, tasks, progress, activity } = data;
  const ownerName = data.members.find((m) => m.user_id === project.owner_id)?.name ?? "—";

  const openEdit = () => {
    setEditForm({
      name: project.name,
      description: project.description,
      deadline: project.deadline,
      priority: project.priority,
      status: project.status,
      owner_id: project.owner_id,
    });
    setEditOpen(true);
  };

  const saveEdit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api(`/api/projects/${project.project_id}`, { method: "PATCH", body: editForm });
      toast.push("success", "Project updated");
      setEditOpen(false);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Update failed");
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    setSaving(true);
    try {
      await api(`/api/projects/${project.project_id}/archive`, { method: "POST" });
      toast.push("success", "Project archived");
      setArchiveOpen(false);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Archive failed");
    } finally {
      setSaving(false);
    }
  };

  const createTask = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api("/api/tasks", {
        method: "POST",
        body: { ...taskForm, project_id: project.project_id, assigned_to: taskForm.assigned_to || undefined },
      });
      toast.push("success", "Task created");
      setTaskOpen(false);
      setTaskForm({ title: "", description: "", assigned_to: "", deadline: "", priority: "Medium", status: "Not Started" });
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setSaving(false);
    }
  };

  const uploadFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("project_id", project.project_id);
      await api("/api/attachments", { form });
      toast.push("success", "File uploaded to Drive");
      void reloadFiles();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  };

  return (
    <div>
      <button onClick={() => navigate("/projects")} className="mb-3 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
        ← Back to projects
      </button>

      <PageHeader
        title={project.name}
        subtitle={project.description || "No description"}
        actions={
          <>
            <Badge value={project.status} />
            <Badge value={project.priority} />
            {canManage && (
              <>
                <Button variant="secondary" onClick={openEdit}>
                  Edit
                </Button>
                {project.status !== "Archived" && (
                  <Button variant="secondary" onClick={() => setArchiveOpen(true)}>
                    <Archive className="h-4 w-4" aria-hidden /> Archive
                  </Button>
                )}
              </>
            )}
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Owner</p>
          <p className="mt-1 truncate text-sm font-medium">{ownerName}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Deadline</p>
          <p className="mt-1 text-sm font-medium">{project.deadline ? formatDate(project.deadline) : "—"}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Start date</p>
          <p className="mt-1 text-sm font-medium">{project.start_date ? formatDate(project.start_date) : "—"}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Progress</p>
          <ProgressBar completed={progress.completed} total={progress.total} className="mt-2.5" />
        </Card>
      </div>

      <Tabs
        tabs={[
          { id: "tasks", label: `Tasks (${tasks.length})` },
          { id: "files", label: `Files (${files?.length ?? 0})` },
          { id: "activity", label: "Activity" },
        ]}
        value={tab}
        onChange={setTab}
      />

      <div className="mt-4">
        {tab === "tasks" && (
          <Card>
            <CardHeader
              title="Project tasks"
              action={
                <Button variant="secondary" onClick={() => setTaskOpen(true)}>
                  <Plus className="h-4 w-4" aria-hidden /> Add task
                </Button>
              }
            />
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {tasks.length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No tasks yet. Add the first one.</p>}
              {tasks.map((task) => {
                const assignee = data.members.find((m) => m.user_id === task.assigned_to)?.name ?? "Unassigned";
                return (
                  <Link key={task.task_id} to={`/tasks/${task.task_id}`} className="flex items-center justify-between gap-3 px-5 py-3 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{task.title}</p>
                      <p className="text-xs text-zinc-500">
                        {assignee} · {task.deadline ? `due ${formatDate(task.deadline)}` : "no deadline"}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge value={task.priority} />
                      <Badge value={task.status} />
                    </div>
                  </Link>
                );
              })}
            </div>
          </Card>
        )}

        {tab === "files" && (
          <Card>
            <CardHeader
              title="Project files"
              action={
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-sm hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800">
                  <Upload className="h-4 w-4" aria-hidden />
                  {uploading ? "Uploading…" : "Upload file"}
                  <input type="file" className="hidden" onChange={uploadFile} disabled={uploading} />
                </label>
              }
            />
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {(files ?? []).length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No files uploaded for this project yet.</p>}
              {(files ?? []).map((file) => (
                <div key={file.attachment_id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{file.file_name}</p>
                    <p className="text-xs text-zinc-500">
                      {data.members.find((m) => m.user_id === file.uploaded_by)?.name ?? "Unknown"} · {timeAgo(file.uploaded_at)}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    onClick={() => void downloadAttachment(file.attachment_id, file.file_name).catch((e) => toast.push("error", e instanceof Error ? e.message : "Download failed"))}
                    aria-label={`Download ${file.file_name}`}
                  >
                    <FileDown className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              ))}
            </div>
          </Card>
        )}

        {tab === "activity" && (
          <Card>
            <CardHeader title="Project activity" />
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {activity.length === 0 && (
                <div className="flex items-center gap-2 px-5 py-6 text-sm text-zinc-500">
                  <History className="h-4 w-4" aria-hidden /> No activity recorded yet.
                </div>
              )}
              {activity.map((entry) => (
                <div key={entry.activity_id} className="px-5 py-3">
                  <p className="text-sm text-zinc-700 dark:text-zinc-300">{entry.description}</p>
                  <p className="mt-0.5 text-xs text-zinc-400">
                    {entry.action} · {timeAgo(entry.timestamp)}
                  </p>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      {/* Edit modal */}
      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit project">
        <form onSubmit={saveEdit} className="space-y-4">
          <Field label="Name">
            <Input required value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
          </Field>
          <Field label="Description">
            <Textarea value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Deadline">
              <Input type="date" value={editForm.deadline} onChange={(e) => setEditForm({ ...editForm, deadline: e.target.value })} />
            </Field>
            <Field label="Priority">
              <Select value={editForm.priority} onChange={(e) => setEditForm({ ...editForm, priority: e.target.value })}>
                {["Low", "Medium", "High", "Critical"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Status">
              <Select value={editForm.status} onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}>
                {["Planning", "Active", "On Hold", "Completed", "Archived"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </Select>
            </Field>
            <Field label="Owner">
              <Select value={editForm.owner_id} onChange={(e) => setEditForm({ ...editForm, owner_id: e.target.value })}>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Save changes
            </Button>
          </div>
        </form>
      </Modal>

      {/* Add task modal */}
      <Modal open={taskOpen} onClose={() => setTaskOpen(false)} title="Add task">
        <form onSubmit={createTask} className="space-y-4">
          <Field label="Title">
            <Input required value={taskForm.title} onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} placeholder="Book the venue" />
          </Field>
          <Field label="Description">
            <Textarea value={taskForm.description} onChange={(e) => setTaskForm({ ...taskForm, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Assignee">
              <Select value={taskForm.assigned_to} onChange={(e) => setTaskForm({ ...taskForm, assigned_to: e.target.value })}>
                <option value="">Unassigned</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Deadline">
              <Input type="date" value={taskForm.deadline} onChange={(e) => setTaskForm({ ...taskForm, deadline: e.target.value })} />
            </Field>
          </div>
          <Field label="Priority">
            <Select value={taskForm.priority} onChange={(e) => setTaskForm({ ...taskForm, priority: e.target.value })}>
              {["Low", "Medium", "High", "Critical"].map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setTaskOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              <ClipboardList className="h-4 w-4" aria-hidden /> Create task
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={archiveOpen}
        onClose={() => setArchiveOpen(false)}
        onConfirm={archive}
        title="Archive project"
        message={`Archive “${project.name}”? Archived projects become read-only for planning but remain in your history.`}
        confirmLabel="Archive"
        loading={saving}
      />
    </div>
  );
}
