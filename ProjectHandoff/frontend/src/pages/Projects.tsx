import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FolderKanban, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Project, Subteam, Task } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useReadOnly } from "../hooks/useReadOnly";
import { useMembers } from "../hooks/useMembers";
import { useSubteamMembers } from "../hooks/useSubteamMembers";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import { Badge, Button, EmptyState, Field, Input, Modal, PageHeader, ProgressBar, Select, SkeletonList, Textarea } from "../components/ui";
import { formatDate, isOverdue } from "../lib/format";

const STATUSES = ["All", "Planning", "Active", "On Hold", "Completed", "Archived"] as const;
const UNASSIGNED = "__unassigned__";
const FULL_ACCESS = ["owner", "admin", "council", "teacher"];

interface ProjectForm {
  name: string;
  description: string;
  requirements: string;
  subteam_id: string;
  owner_id: string;
  start_date: string;
  deadline: string;
  priority: string;
  status: string;
}

const EMPTY_FORM: ProjectForm = {
  name: "",
  description: "",
  requirements: "",
  subteam_id: "",
  owner_id: "",
  start_date: "",
  deadline: "",
  priority: "Medium",
  status: "Planning",
};

export function Projects() {
  const { user, team, subteams: mySubteams } = useAuth();
  const readOnly = useReadOnly();
  const members = useMembers();
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState<(typeof STATUSES)[number]>("All");
  const [subteamFilter, setSubteamFilter] = useState("");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<ProjectForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fullAccess = FULL_ACCESS.includes(user?.role ?? "");
  const canViewAll = fullAccess || user?.role === "coordinator";

  const { data: teamSubteams } = useResource<Subteam[]>(
    () => (team ? api(`/api/teams/${encodeURIComponent(team.team_id)}/subteams`) : Promise.resolve([])),
    [team?.team_id],
    0,
  );
  const visibleSubteams = useMemo(
    () => canViewAll
      ? teamSubteams ?? []
      : (teamSubteams ?? []).filter((s) => mySubteams.some((m) => m.subteam_id === s.subteam_id)),
    [canViewAll, teamSubteams, mySubteams],
  );
  const subteamName = (id: string) => visibleSubteams.find((s) => s.subteam_id === id)?.name ?? "Unassigned";

  const createMembers = useSubteamMembers(form.subteam_id || null);
  const ownerOptions = form.subteam_id ? createMembers.members : members;

  const projectUrl = useMemo(() => {
    const params = new URLSearchParams();
    if (subteamFilter) params.set("subteam_id", subteamFilter);
    const qs = params.toString();
    return `/api/projects${qs ? `?${qs}` : ""}`;
  }, [subteamFilter]);

  const { data: projects, loading, error, reload } = useResource<Project[]>(() => api(projectUrl), [projectUrl], 15000);
  const { data: tasks } = useResource<Task[]>(() => api("/api/tasks"), [], 30000);

  const progressByProject = useMemo(() => {
    const map = new Map<string, { total: number; completed: number }>();
    for (const task of tasks ?? []) {
      if (!task.project_id) continue;
      const entry = map.get(task.project_id) ?? { total: 0, completed: 0 };
      entry.total += 1;
      if (task.status === "Completed") entry.completed += 1;
      map.set(task.project_id, entry);
    }
    return map;
  }, [tasks]);

  const filtered = useMemo(() => {
    let list = projects ?? [];
    if (statusFilter !== "All") list = list.filter((p) => p.status === statusFilter);
    if (query.trim()) {
      const needle = query.toLowerCase();
      list = list.filter(
        (p) => p.name.toLowerCase().includes(needle) || p.description.toLowerCase().includes(needle),
      );
    }
    return list;
  }, [projects, statusFilter, query]);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.subteam_id && (teamSubteams?.length ?? 0) > 0) {
      setFormError("Choose a subteam for this project");
      return;
    }
    if (form.subteam_id && !form.requirements.trim()) {
      setFormError("Requirements are required for a subteam project");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await api("/api/projects", {
        method: "POST",
        body: { ...form, owner_id: form.owner_id || undefined },
      });
      toast.push("success", "Project created");
      setCreateOpen(false);
      setForm(EMPTY_FORM);
      void reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Projects"
        subtitle="Coordinate workstreams, owners and deadlines"
        actions={
          fullAccess && !readOnly && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New project
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {STATUSES.map((status) => (
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
        <Select
          value={subteamFilter}
          onChange={(e) => setSubteamFilter(e.target.value)}
          className="w-full sm:w-48"
          aria-label="Filter by subteam"
        >
          <option value="">All subteams</option>
          <option value={UNASSIGNED}>Unassigned</option>
          {visibleSubteams.map((subteam) => (
            <option key={subteam.subteam_id} value={subteam.subteam_id}>
              {subteam.name}
            </option>
          ))}
        </Select>
        <Input
          placeholder="Search projects…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full sm:ml-auto sm:max-w-xs"
          aria-label="Search projects"
        />
      </div>

      {loading && !projects ? (
        <SkeletonList rows={3} />
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<FolderKanban className="h-10 w-10" aria-hidden />}
          title={projects?.length ? "No projects match your filters" : subteamFilter ? "No projects in this scope" : "No projects yet"}
          description={
            projects?.length
              ? "Try a different status or search term."
              : subteamFilter
                ? "No projects are assigned to this scope yet."
                : "Create your first project to start tracking work."
          }
          action={
            fullAccess && !readOnly && !projects?.length && !subteamFilter ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden /> New project
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {filtered.map((project) => {
            const progress = progressByProject.get(project.project_id) ?? { total: 0, completed: 0 };
            const overdue = isOverdue(project.deadline, project.status);
            return (
              <Link key={project.project_id} to={`/projects/${project.project_id}`} className="card-base block min-w-0 p-5 transition hover:border-brand-300 dark:hover:border-brand-700">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="line-clamp-2 break-words font-medium text-stone-900 dark:text-stone-50">{project.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-sm text-stone-500 dark:text-stone-400">
                      {project.description || "No description"}
                    </p>
                  </div>
                  <Badge value={project.status} className="shrink-0" />
                </div>
                <p className="mt-3 line-clamp-2 whitespace-pre-wrap break-words rounded-lg bg-stone-50 px-3 py-2 text-xs text-stone-600 dark:bg-stone-800/60 dark:text-stone-300">
                  <span className="font-semibold">Requirements: </span>
                  {project.requirements || "No requirements recorded"}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                  {project.subteam_id ? (
                    <span className="rounded-full bg-brand-50 px-2.5 py-1 text-[11px] font-medium text-brand-700 ring-1 ring-inset ring-brand-600/15 dark:bg-brand-500/10 dark:text-brand-300 dark:ring-brand-400/20">
                      {subteamName(project.subteam_id)}
                    </span>
                  ) : (
                    <span className="rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-medium text-stone-600 ring-1 ring-inset ring-stone-500/15 dark:bg-stone-800 dark:text-stone-300">
                      Unassigned
                    </span>
                  )}
                  <Badge value={project.priority} className="shrink-0" />
                  <span>·</span>
                  <span className={`min-w-0 ${overdue ? "font-medium text-red-600 dark:text-red-400" : ""}`}>
                    {project.deadline ? (overdue ? `Overdue (was due ${formatDate(project.deadline)})` : `Due ${formatDate(project.deadline)}`) : "No deadline"}
                  </span>
                </div>
                <ProgressBar completed={progress.completed} total={progress.total} className="mt-3" />
              </Link>
            );
          })}
        </div>
      )}

      <Modal open={createOpen && fullAccess && !readOnly} onClose={() => setCreateOpen(false)} title="Create project" wide>
        <form onSubmit={create} className="space-y-4">
          {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
          <Field label="Name">
            <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Spring concert" />
          </Field>
          <Field label="Description">
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What is this project about?" />
          </Field>
          <Field
            label="Subteam"
            hint={teamSubteams?.length ? "Required for every project in a team with subteams." : "This team has no subteams yet."}
          >
            <Select
              required={(teamSubteams?.length ?? 0) > 0}
              value={form.subteam_id}
              onChange={(e) => setForm({ ...form, subteam_id: e.target.value, owner_id: "" })}
            >
              <option value="">{teamSubteams?.length ? "Choose a subteam…" : "No subteam (legacy)"}</option>
              {(teamSubteams ?? []).map((subteam) => (
                <option key={subteam.subteam_id} value={subteam.subteam_id}>
                  {subteam.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Requirements" hint="Required for a subteam project — what must this project deliver?">
            <Textarea
              required={!!form.subteam_id}
              value={form.requirements}
              onChange={(e) => setForm({ ...form, requirements: e.target.value })}
              placeholder="Deliverables, constraints and acceptance criteria"
            />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Start date">
              <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            </Field>
            <Field label="Deadline">
              <Input type="date" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} />
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {["Low", "Medium", "High", "Critical"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
            </Field>
            <Field label="Status">
              <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {["Planning", "Active", "On Hold"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </Select>
            </Field>
          </div>
          <Field
            label="Project owner"
            hint={form.subteam_id ? "Only members of this subteam can own scoped projects." : "Defaults to you."}
          >
            <Select value={form.owner_id} onChange={(e) => setForm({ ...form, owner_id: e.target.value })}>
              <option value="">Me ({user?.name})</option>
              {ownerOptions.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name || m.user_id}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Create project
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
