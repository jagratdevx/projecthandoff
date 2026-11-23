import { Link } from "react-router-dom";
import {
  ArrowLeftRight,
  ArrowRight,
  CalendarDays,
  CircleAlert,
  ClipboardList,
  FolderKanban,
  ListTodo,
  Users,
} from "lucide-react";
import { api } from "../api/client";
import type { DashboardData } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { Badge, Card, CardHeader, EmptyState, PageHeader, ProgressBar, SkeletonList } from "../components/ui";
import { formatDate, timeAgo } from "../lib/format";

export function Dashboard() {
  const { user, team } = useAuth();
  const { data, loading, error, reload } = useResource<DashboardData>(() => api("/api/dashboard"), [], 15000);

  if (!team) {
    return (
      <EmptyState
        icon={<Users className="h-10 w-10" aria-hidden />}
        title="You are not part of a team yet"
        description="Create a team to start coordinating projects, events and handovers."
        action={
          <Link to="/team">
            <span className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm ring-1 ring-inset ring-white/10 transition hover:bg-brand-700">
              Create a team <ArrowRight className="h-4 w-4" aria-hidden />
            </span>
          </Link>
        }
      />
    );
  }

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card-base h-24 animate-pulse last:col-span-2 lg:last:col-span-1" />
          ))}
        </div>
        <SkeletonList rows={3} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Failed to load dashboard"}</p>
        <button
          onClick={() => void reload()}
          className="inline-flex items-center rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm ring-1 ring-inset ring-white/10 transition hover:bg-brand-700"
        >
          Try again
        </button>
      </div>
    );
  }

  const { stats } = data;

  const statCards = [
    { label: "Active projects", value: stats.active_projects, icon: FolderKanban, to: "/projects" },
    { label: "My open tasks", value: stats.my_open_tasks, icon: ListTodo, to: "/tasks" },
    { label: "Pending handovers", value: stats.pending_handovers, icon: ArrowLeftRight, to: "/handovers" },
    { label: "Due in 14 days", value: stats.upcoming_deadlines, icon: ClipboardList, to: "/tasks" },
    { label: "Overdue", value: stats.overdue_tasks, icon: CircleAlert, to: "/tasks", danger: stats.overdue_tasks > 0 },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome back, ${user?.name?.split(" ")[0] ?? "there"}`}
        subtitle={`${team.name} · ${stats.team_size} member${stats.team_size === 1 ? "" : "s"}`}
        actions={undefined}
      />

      {error && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/40 dark:text-amber-200">
          <span>Showing the last loaded data — {error}</span>
          <button onClick={() => void reload()} className="font-medium underline underline-offset-2 hover:no-underline">
            Retry
          </button>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
        {statCards.map(({ label, value, icon: Icon, to, danger }) => (
          <Link key={label} to={to} className="card-base card-interactive group p-4 sm:p-5 last:col-span-2 lg:last:col-span-1">
            <div className="flex items-start justify-between">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-stone-100 text-stone-500 transition group-hover:bg-brand-50 group-hover:text-brand-700 dark:bg-stone-800 dark:text-stone-400 dark:group-hover:bg-brand-500/10 dark:group-hover:text-brand-300">
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              {danger && <span className="mt-1.5 h-2 w-2 rounded-full bg-red-500 ring-4 ring-red-500/10" aria-label="Needs attention" />}
            </div>
            <p
              className={`mt-4 text-[28px] font-semibold leading-none tracking-tight tabular-nums ${
                danger && value > 0 ? "text-red-600 dark:text-red-400" : "text-stone-900 dark:text-stone-50"
              }`}
            >
              {value}
            </p>
            <p className="mt-2 text-xs font-medium text-stone-500 dark:text-stone-400">{label}</p>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Projects */}
        <Card>
          <CardHeader
            title="Active projects"
            action={
              <Link to="/projects" className="link-accent text-xs">
                View all
              </Link>
            }
          />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.projects.length === 0 && (
              <p className="px-5 py-6 text-sm text-stone-500">No active projects. Create one from the Projects page.</p>
            )}
            {data.projects.map((project) => (
              <Link key={project.project_id} to={`/projects/${project.project_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50/80 dark:hover:bg-stone-800/50">
                <div className="flex items-center justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-medium text-stone-900 dark:text-stone-100">{project.name}</p>
                  <Badge value={project.priority} className="shrink-0" />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <ProgressBar completed={project.progress?.completed ?? 0} total={project.progress?.total ?? 0} className="max-w-[180px]" />
                  <span className="text-xs text-stone-500">due {formatDate(project.deadline)}</span>
                </div>
              </Link>
            ))}
          </div>
        </Card>

        {/* Handovers */}
        <Card>
          <CardHeader
            title="Pending handovers"
            action={
              <Link to="/handovers" className="link-accent text-xs">
                Open inbox
              </Link>
            }
          />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.incoming_handovers.length === 0 && data.outgoing_handovers.length === 0 && (
              <p className="px-5 py-6 text-sm text-stone-500">No pending handovers. Nothing is waiting on you.</p>
            )}
            {data.incoming_handovers.map((handover) => (
              <Link key={handover.handover_id} to={`/handovers/${handover.handover_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50/80 dark:hover:bg-stone-800/50">
                <div className="flex items-center justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-medium text-stone-900 dark:text-stone-100">{handover.task_title || "Task handover"}</p>
                  <Badge value={handover.status} className="shrink-0" />
                </div>
                <p className="mt-0.5 text-xs text-stone-500">
                  {handover.previous_owner_name} → you · sent {timeAgo(handover.created_at)}
                </p>
              </Link>
            ))}
            {data.outgoing_handovers.map((handover) => (
              <Link key={handover.handover_id} to={`/handovers/${handover.handover_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50/80 dark:hover:bg-stone-800/50">
                <div className="flex items-center justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-medium text-stone-900 dark:text-stone-100">{handover.task_title || "Task handover"}</p>
                  <Badge value={handover.status} className="shrink-0" />
                </div>
                <p className="mt-0.5 text-xs text-stone-500">
                  You → {handover.proposed_owner_name} · sent {timeAgo(handover.created_at)}
                </p>
              </Link>
            ))}
          </div>
        </Card>

        {/* My tasks */}
        <Card>
          <CardHeader
            title="My open tasks"
            action={
              <Link to="/tasks" className="link-accent text-xs">
                View all
              </Link>
            }
          />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.my_tasks.length === 0 && <p className="px-5 py-6 text-sm text-stone-500">Nothing assigned to you right now.</p>}
            {data.my_tasks.map((task) => (
              <Link key={task.task_id} to={`/tasks/${task.task_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50/80 dark:hover:bg-stone-800/50">
                <div className="flex items-center justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-medium text-stone-900 dark:text-stone-100">{task.title}</p>
                  <Badge value={task.priority} className="shrink-0" />
                </div>
                <p className="mt-0.5 text-xs text-stone-500">due {formatDate(task.deadline)} · {task.status}</p>
              </Link>
            ))}
          </div>
        </Card>

        {/* Upcoming deadlines */}
        <Card>
          <CardHeader title="Upcoming deadlines (14 days)" />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.upcoming_deadlines.length === 0 && <p className="px-5 py-6 text-sm text-stone-500">No deadlines in the next two weeks.</p>}
            {data.upcoming_deadlines.map((task) => (
              <Link key={task.task_id} to={`/tasks/${task.task_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50/80 dark:hover:bg-stone-800/50">
                <div className="flex items-center justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-medium text-stone-900 dark:text-stone-100">{task.title}</p>
                  <span className="shrink-0 text-xs text-stone-500">{formatDate(task.deadline)}</span>
                </div>
                <p className="mt-0.5 text-xs text-stone-500">{task.assignee_name || "Unassigned"}</p>
              </Link>
            ))}
          </div>
        </Card>

        {/* Events & departments */}
        <Card>
          <CardHeader
            title="Event progress"
            action={
              <Link to="/events" className="link-accent text-xs">
                View all
              </Link>
            }
          />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.events.length === 0 && (
              <p className="px-5 py-6 text-sm text-stone-500">No events yet. Plan one from the Events page.</p>
            )}
            {data.events.map((event) => (
              <Link key={event.event_id} to={`/events/${event.event_id}`} className="block px-5 py-3.5 transition hover:bg-stone-50/80 dark:hover:bg-stone-800/50">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2 truncate text-sm font-medium text-stone-900 dark:text-stone-100">
                    <CalendarDays className="h-3.5 w-3.5 shrink-0 text-stone-400" aria-hidden />
                    {event.name}
                  </span>
                  <Badge value={event.status} className="shrink-0" />
                </div>
                <ProgressBar completed={event.progress?.completed ?? 0} total={event.progress?.total ?? 0} className="mt-2" />
              </Link>
            ))}
          </div>
        </Card>

        {/* Activity */}
        <Card>
          <CardHeader
            title="Recent team activity"
            action={
              <Link to="/activity" className="link-accent text-xs">
                Full history
              </Link>
            }
          />
          <div className="divide-y divide-stone-100 dark:divide-stone-800">
            {data.activity.length === 0 && <p className="px-5 py-6 text-sm text-stone-500">No activity recorded yet.</p>}
            {data.activity.map((entry) => (
              <div key={entry.activity_id} className="px-5 py-3">
                <p className="break-words text-sm text-stone-700 [overflow-wrap:anywhere] dark:text-stone-300">{entry.description}</p>
                <p className="mt-0.5 text-xs text-stone-400">{timeAgo(entry.timestamp)}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Departments */}
      {data.departments.length > 0 && (
        <Card>
          <CardHeader title="Department progress" />
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            {data.departments.map((department) => (
              <div key={department.department_id} className="rounded-lg border border-stone-200 p-3.5 dark:border-stone-800">
                <div className="flex items-center justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-stone-900 dark:text-stone-100">{department.name}</p>
                  <span className="shrink-0 text-xs text-stone-500">{department.member_count ?? 0} members</span>
                </div>
                <p className="mt-0.5 text-xs text-stone-500">Coordinator: {department.coordinator_name || "—"}</p>
                <ProgressBar completed={department.progress?.completed ?? 0} total={department.progress?.total ?? 0} className="mt-2.5" />
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
