import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ListChecks, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Project, Task } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useMembers } from "../hooks/useMembers";
import { useSubteamMembers } from "../hooks/useSubteamMembers";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  SkeletonList,
  Textarea,
} from "../components/ui";
import { formatDate, isOverdue } from "../lib/format";

const TASK_STATUSES = ["All", "Not Started", "In Progress", "Blocked", "Under Review", "Completed"] as const;

interface TaskForm {
  title: string;
  description: string;
  project_id: string;
  assigned_to: string;
  deadline: string;
  priority: string;
  status: string;
}

const EMPTY_TASK: TaskForm = {
  title: "",
  description: "",
  project_id: "",
  assigned_to: "",
  deadline: "",
  priority: "Medium",
  status: "Not Started",
};

export function Tasks() {
  const { user } = useAuth();
  const members = useMembers();
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState<(typeof TASK_STATUSES)[number]>("All");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<TaskForm>(EMPTY_TASK);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const queryPart = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "All") params.set("status", statusFilter);
    if (assigneeFilter) params.set("assigned_to", assigneeFilter);
    if (projectFilter) params.set("project_id", projectFilter);
    if (query.trim()) params.set("q", query.trim());
    const qs = params.toString();
    return `/api/tasks${qs ? `?${qs}` : ""}`;
  }, [statusFilter, assigneeFilter, projectFilter, query]);

  const { data: tasks, loading, error, reload } = useResource<Task[]>(() => api(queryPart), [queryPart], 15000);
  const { data: projects } = useResource<Project[]>(() => api("/api/projects"), [], 60000);
  // Projects are already scoped by the backend; assignees come from the
  // selected project's subteam so the server never rejects the selection.
  const selectedSubteamId = projects?.find((p) => p.project_id === form.project_id)?.subteam_id ?? "";
  const { members: subteamAssignees } = useSubteamMembers(selectedSubteamId || null);
  const assignable = selectedSubteamId ? subteamAssignees : members;

  const projectName = (id: string) => projects?.find((p) => p.project_id === id)?.name;

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      await api("/api/tasks", {
        method: "POST",
        body: {
          ...form,
          project_id: form.project_id || undefined,
          assigned_to: form.assigned_to || undefined,
        },
      });
      toast.push("success", "Task created");
      setCreateOpen(false);
      setForm(EMPTY_TASK);
      void reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Tasks"
        subtitle="Everything assigned across the team"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden /> New task
          </Button>
        }
      />

      <div className="mb-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {TASK_STATUSES.map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
                statusFilter === status
                  ? "bg-brand-600 text-white"
                  : "bg-stone-100 text-stone-600 hover:bg-stone-200 dark:bg-stone-800 dark:text-stone-300 dark:hover:bg-stone-700"
              }`}
            >
              {status}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={assigneeFilter}
            onChange={(e) => setAssigneeFilter(e.target.value)}
            className="w-full sm:w-auto sm:max-w-[200px]"
            aria-label="Filter by assignee"
          >
            <option value="">Everyone</option>
            <option value={user?.user_id ?? ""}>Assigned to me</option>
            {members
              .filter((m) => m.user_id !== user?.user_id)
              .map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name}
                </option>
              ))}
          </Select>
          <Select
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}
            className="w-full sm:w-auto sm:max-w-[220px]"
            aria-label="Filter by project"
          >
            <option value="">All projects</option>
            {(projects ?? []).map((p) => (
              <option key={p.project_id} value={p.project_id}>
                {p.name}
              </option>
            ))}
          </Select>
          <Input
            placeholder="Search tasks…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full sm:ml-auto sm:max-w-xs"
            aria-label="Search tasks"
          />
        </div>
      </div>

      {loading && !tasks ? (
        <SkeletonList rows={5} />
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : (tasks ?? []).length === 0 ? (
        <EmptyState
          icon={<ListChecks className="h-10 w-10" aria-hidden />}
          title="No tasks found"
          description="Try different filters, or create a task to get work moving."
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New task
            </Button>
          }
        />
      ) : (
        <div className="card-base overflow-hidden">
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {(tasks ?? []).map((task) => {
              const assignee = members.find((m) => m.user_id === task.assigned_to)?.name ?? "Unassigned";
              const overdue = isOverdue(task.deadline, task.status);
              return (
                <Link key={task.task_id} to={`/tasks/${task.task_id}`} className="flex items-center justify-between gap-3 px-4 py-3 transition hover:bg-stone-50 dark:hover:bg-stone-800/60 sm:px-5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-stone-900 dark:text-stone-100">{task.title}</p>
                    <p className="truncate text-xs text-stone-500">
                      {task.project_id ? `${projectName(task.project_id) ?? "Project"} · ` : ""}
                      {assignee} · {task.deadline ? (overdue ? "overdue " : "due ") + formatDate(task.deadline) : "no deadline"}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge value={task.priority} className="hidden sm:inline-flex" />
                    <Badge value={task.status} />
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create task" wide>
        <form onSubmit={create} className="space-y-4">
          {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
          <Field label="Title">
            <Input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Print flyers for the fair" />
          </Field>
          <Field label="Description">
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Project" hint="Only projects in your subteams are shown.">
              <Select value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value, assigned_to: "" })}>
                <option value="">None</option>
                {(projects ?? []).map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Assignee" hint={selectedSubteamId ? "Members of the selected project's subteam only." : undefined}>
              <Select value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}>
                <option value="">Unassigned</option>
                {assignable.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Deadline">
              <Input type="date" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} />
            </Field>
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {["Low", "Medium", "High", "Critical"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
            </Field>
            <Field label="Status">
              <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {["Not Started", "In Progress", "Blocked", "Under Review"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Create task
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
