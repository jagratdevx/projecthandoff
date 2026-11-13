import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Plus, Trash2, UserPlus } from "lucide-react";
import { api } from "../api/client";
import type { Department, Event, Task, User } from "../api/types";
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
  ProgressBar,
  Select,
  SkeletonList,
  Textarea,
} from "../components/ui";
import { formatDate } from "../lib/format";

interface EventDetailData {
  event: Event;
  departments: Department[];
  tasks: Task[];
  progress: { total: number; completed: number };
  members: User[];
}

export function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const toast = useToast();

  const { data, loading, error, reload } = useResource<EventDetailData>(() => api(`/api/events/${id}`), [id], 15000);

  const [deptOpen, setDeptOpen] = useState(false);
  const [deptForm, setDeptForm] = useState({ name: "", description: "", coordinator_id: "" });
  const [taskOpen, setTaskOpen] = useState(false);
  const [taskForm, setTaskForm] = useState({ title: "", description: "", department_id: "", assigned_to: "", deadline: "", priority: "Medium" });
  const [memberModal, setMemberModal] = useState<Department | null>(null);
  const [saving, setSaving] = useState(false);
  const [removeTaskConfirm, setRemoveTaskConfirm] = useState<Task | null>(null);
  const [deptMemberAdds, setDeptMemberAdds] = useState("");

  if (loading && !data) return <SkeletonList rows={4} />;
  if (error || !data) return <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Event not found"}</p>;

  const { event, departments, tasks, progress, members } = data;
  const nameOf = (userId: string) => members.find((m) => m.user_id === userId)?.name ?? "Unknown";
  const canManage = user?.role === "owner" || user?.role === "admin" || event.owner_id === user?.user_id;

  const createDepartment = async (formEvent: React.FormEvent) => {
    formEvent.preventDefault();
    setSaving(true);
    try {
      await api(`/api/events/${event.event_id}/departments`, {
        method: "POST",
        body: { ...deptForm, coordinator_id: deptForm.coordinator_id || undefined },
      });
      toast.push("success", "Department added");
      setDeptOpen(false);
      setDeptForm({ name: "", description: "", coordinator_id: "" });
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Failed to create department");
    } finally {
      setSaving(false);
    }
  };

  const createTask = async (formEvent: React.FormEvent) => {
    formEvent.preventDefault();
    setSaving(true);
    try {
      await api("/api/tasks", {
        method: "POST",
        body: {
          ...taskForm,
          event_id: event.event_id,
          department_id: taskForm.department_id || undefined,
          assigned_to: taskForm.assigned_to || undefined,
        },
      });
      toast.push("success", "Task created");
      setTaskOpen(false);
      setTaskForm({ title: "", description: "", department_id: "", assigned_to: "", deadline: "", priority: "Medium" });
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setSaving(false);
    }
  };

  const addDeptMember = async (department: Department, userId: string) => {
    try {
      await api(`/api/departments/${department.department_id}/members`, { method: "POST", body: { user_id: userId } });
      toast.push("success", "Member added to department");
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Failed to add member");
    }
  };

  const removeDeptMember = async (department: Department, userId: string) => {
    try {
      await api(`/api/departments/${department.department_id}/members/${userId}`, { method: "DELETE" });
      toast.push("success", "Member removed");
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Failed to remove member");
    }
  };

  const deleteTask = async (task: Task) => {
    try {
      await api(`/api/tasks/${task.task_id}`, { method: "DELETE" });
      toast.push("success", "Task deleted");
      setRemoveTaskConfirm(null);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <div>
      <button onClick={() => navigate("/events")} className="mb-3 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
        ← Back to events
      </button>

      <PageHeader
        title={event.name}
        subtitle={event.description || "No description"}
        actions={<Badge value={event.status} />}
      />

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Dates</p>
          <p className="mt-1 text-sm font-medium">
            {event.start_date ? formatDate(event.start_date) : "TBD"}
            {event.end_date ? ` → ${formatDate(event.end_date)}` : ""}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Owner</p>
          <p className="mt-1 text-sm font-medium">{nameOf(event.owner_id)}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Departments</p>
          <p className="mt-1 text-sm font-medium">{departments.filter((d) => d.status === "Active").length}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-zinc-500">Overall progress</p>
          <ProgressBar completed={progress.completed} total={progress.total} className="mt-2.5" />
        </Card>
      </div>

      {/* Departments */}
      <Card className="mb-6">
        <CardHeader
          title="Departments"
          action={
            <Button variant="secondary" onClick={() => setDeptOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> Add department
            </Button>
          }
        />
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {departments.length === 0 && (
            <p className="px-5 py-6 text-sm text-zinc-500">
              No departments yet. Split the event into logistics, sponsors, tech and other areas.
            </p>
          )}
          {departments.map((department) => (
            <div key={department.department_id} className="px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{department.name}</p>
                  <p className="text-xs text-zinc-500">
                    Coordinator: {department.coordinator_name || "—"} · {(department.member_ids ?? []).length} members
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" onClick={() => { setMemberModal(department); setDeptMemberAdds(""); }} aria-label={`Manage members of ${department.name}`}>
                    <UserPlus className="h-4 w-4" aria-hidden />
                  </Button>
                  {canManage && department.status === "Active" && (
                    <Button
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await api(`/api/departments/${department.department_id}`, { method: "PATCH", body: { status: "Archived" } });
                          toast.push("success", "Department archived");
                          void reload();
                        } catch (err) {
                          toast.push("error", err instanceof Error ? err.message : "Archive failed");
                        }
                      }}
                      aria-label={`Archive ${department.name}`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  )}
                </div>
              </div>
              <ProgressBar completed={department.progress?.completed ?? 0} total={department.progress?.total ?? 0} className="mt-2.5" />
            </div>
          ))}
        </div>
      </Card>

      {/* Tasks */}
      <Card>
        <CardHeader
          title={`Event tasks (${tasks.length})`}
          action={
            <Button variant="secondary" onClick={() => setTaskOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> Add task
            </Button>
          }
        />
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {tasks.length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No tasks for this event yet.</p>}
          {tasks.map((task) => {
            const department = departments.find((d) => d.department_id === task.department_id);
            return (
              <div key={task.task_id} className="flex items-center justify-between gap-3 px-5 py-3">
                <Link to={`/tasks/${task.task_id}`} className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-zinc-900 hover:underline dark:text-zinc-100">{task.title}</p>
                  <p className="text-xs text-zinc-500">
                    {department ? `${department.name} · ` : ""}
                    {task.assigned_to ? nameOf(task.assigned_to) : "Unassigned"}
                    {task.deadline ? ` · due ${formatDate(task.deadline)}` : ""}
                  </p>
                </Link>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge value={task.priority} className="hidden sm:inline-flex" />
                  <Badge value={task.status} />
                  {user && (task.created_by === user.user_id || user.role === "owner" || user.role === "admin") && (
                    <Button variant="ghost" className="p-1" onClick={() => setRemoveTaskConfirm(task)} aria-label={`Delete ${task.title}`}>
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Add department modal */}
      <Modal open={deptOpen} onClose={() => setDeptOpen(false)} title="Add department">
        <form onSubmit={createDepartment} className="space-y-4">
          <Field label="Name">
            <Input required value={deptForm.name} onChange={(e) => setDeptForm({ ...deptForm, name: e.target.value })} placeholder="Logistics" />
          </Field>
          <Field label="Description">
            <Textarea value={deptForm.description} onChange={(e) => setDeptForm({ ...deptForm, description: e.target.value })} />
          </Field>
          <Field label="Coordinator">
            <Select value={deptForm.coordinator_id} onChange={(e) => setDeptForm({ ...deptForm, coordinator_id: e.target.value })}>
              <option value="">Unassigned for now</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setDeptOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Add department
            </Button>
          </div>
        </form>
      </Modal>

      {/* Add task modal */}
      <Modal open={taskOpen} onClose={() => setTaskOpen(false)} title="Add event task" wide>
        <form onSubmit={createTask} className="space-y-4">
          <Field label="Title">
            <Input required value={taskForm.title} onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} placeholder="Confirm sponsor booths" />
          </Field>
          <Field label="Description">
            <Textarea value={taskForm.description} onChange={(e) => setTaskForm({ ...taskForm, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Department">
              <Select value={taskForm.department_id} onChange={(e) => setTaskForm({ ...taskForm, department_id: e.target.value })}>
                <option value="">Whole event</option>
                {departments.filter((d) => d.status === "Active").map((d) => (
                  <option key={d.department_id} value={d.department_id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </Field>
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
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Deadline">
              <Input type="date" value={taskForm.deadline} onChange={(e) => setTaskForm({ ...taskForm, deadline: e.target.value })} />
            </Field>
            <Field label="Priority">
              <Select value={taskForm.priority} onChange={(e) => setTaskForm({ ...taskForm, priority: e.target.value })}>
                {["Low", "Medium", "High", "Critical"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setTaskOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Create task
            </Button>
          </div>
        </form>
      </Modal>

      {/* Department members modal */}
      <Modal open={!!memberModal} onClose={() => setMemberModal(null)} title={`Members · ${memberModal?.name ?? ""}`}>
        <div className="space-y-4">
          <div className="space-y-1.5">
            {(memberModal?.member_ids ?? []).length === 0 && (
              <p className="text-sm text-zinc-500">No members assigned to this department yet.</p>
            )}
            {(memberModal?.member_ids ?? []).map((memberId) => (
              <div key={memberId} className="flex items-center justify-between rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-800">
                <span className="text-sm">{nameOf(memberId)}</span>
                <Button variant="ghost" className="p-1" onClick={() => memberModal && void removeDeptMember(memberModal, memberId)} aria-label={`Remove ${nameOf(memberId)}`}>
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </div>
            ))}
          </div>
          <Field label="Add a member">
            <Select
              value={deptMemberAdds}
              onChange={(e) => {
                const userId = e.target.value;
                if (userId && memberModal) {
                  void addDeptMember(memberModal, userId);
                  setDeptMemberAdds("");
                }
              }}
            >
              <option value="">Choose a team member…</option>
              {members
                .filter((m) => !(memberModal?.member_ids ?? []).includes(m.user_id))
                .map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.name}
                  </option>
                ))}
            </Select>
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!removeTaskConfirm}
        onClose={() => setRemoveTaskConfirm(null)}
        onConfirm={() => removeTaskConfirm && void deleteTask(removeTaskConfirm)}
        title="Delete task"
        message={`Delete “${removeTaskConfirm?.title ?? ""}”?`}
        confirmLabel="Delete"
      />
    </div>
  );
}
