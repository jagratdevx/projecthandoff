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
  const { data, loading, error } = useResource<DashboardData>(() => api("/api/dashboard"), [], 15000);

  if (!team) {
    return (
      <EmptyState
        icon={<Users className="h-10 w-10" aria-hidden />}
        title="You are not part of a team yet"
        description="Create a team to start coordinating projects, events and handovers."
        action={
          <Link to="/team">
            <span className="inline-flex items-center rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700">
              Create a team <ArrowRight className="ml-1.5 h-4 w-4" aria-hidden />
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
            <div key={i} className="card-base h-24 animate-pulse" />
          ))}
        </div>
        <SkeletonList rows={3} />
      </div>
    );
  }

  if (error || !data) {
    return <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Failed to load dashboard"}</p>;
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

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {statCards.map(({ label, value, icon: Icon, to, danger }) => (
          <Link key={label} to={to} className="card-base p-4 transition hover:border-indigo-300 dark:hover:border-indigo-700">
            <div className="flex items-center justify-between">
              <Icon className="h-4 w-4 text-zinc-400" aria-hidden />
              {danger && <span className="rounded-full bg-red-100 px-2 text-xs font-semibold text-red-700 dark:bg-red-950 dark:text-red-300">!</span>}
            </div>
            <p className={`mt-2 text-2xl font-semibold tabular-nums ${danger && value > 0 ? "text-red-600 dark:text-red-400" : "text-zinc-900 dark:text-zinc-50"}`}>
              {value}
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Projects */}
        <Card>
          <CardHeader
            title="Active projects"
            action={
              <Link to="/projects" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                View all
              </Link>
            }
          />
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.projects.length === 0 && (
              <p className="px-5 py-6 text-sm text-zinc-500">No active projects. Create one from the Projects page.</p>
            )}
            {data.projects.map((project) => (
              <Link key={project.project_id} to={`/projects/${project.project_id}`} className="block px-5 py-3.5 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{project.name}</p>
                  <Badge value={project.priority} />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <ProgressBar completed={project.progress?.completed ?? 0} total={project.progress?.total ?? 0} className="max-w-[180px]" />
                  <span className="text-xs text-zinc-500">due {formatDate(project.deadline)}</span>
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
              <Link to="/handovers" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                Open inbox
              </Link>
            }
          />
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.incoming_handovers.length === 0 && data.outgoing_handovers.length === 0 && (
              <p className="px-5 py-6 text-sm text-zinc-500">No pending handovers. Nothing is waiting on you.</p>
            )}
            {data.incoming_handovers.map((handover) => (
              <Link key={handover.handover_id} to={`/handovers/${handover.handover_id}`} className="block px-5 py-3.5 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{handover.task_title || "Task handover"}</p>
                  <Badge value={handover.status} />
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {handover.previous_owner_name} → you · sent {timeAgo(handover.created_at)}
                </p>
              </Link>
            ))}
            {data.outgoing_handovers.map((handover) => (
              <Link key={handover.handover_id} to={`/handovers/${handover.handover_id}`} className="block px-5 py-3.5 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{handover.task_title || "Task handover"}</p>
                  <Badge value={handover.status} />
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">
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
              <Link to="/tasks" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                View all
              </Link>
            }
          />
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.my_tasks.length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">Nothing assigned to you right now.</p>}
            {data.my_tasks.map((task) => (
              <Link key={task.task_id} to={`/tasks/${task.task_id}`} className="block px-5 py-3.5 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{task.title}</p>
                  <Badge value={task.priority} />
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">due {formatDate(task.deadline)} · {task.status}</p>
              </Link>
            ))}
          </div>
        </Card>

        {/* Upcoming deadlines */}
        <Card>
          <CardHeader title="Upcoming deadlines (14 days)" />
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.upcoming_deadlines.length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No deadlines in the next two weeks.</p>}
            {data.upcoming_deadlines.map((task) => (
              <Link key={task.task_id} to={`/tasks/${task.task_id}`} className="block px-5 py-3.5 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{task.title}</p>
                  <span className="text-xs text-zinc-500">{formatDate(task.deadline)}</span>
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">{task.assignee_name || "Unassigned"}</p>
              </Link>
            ))}
          </div>
        </Card>

        {/* Events & departments */}
        <Card>
          <CardHeader
            title="Event progress"
            action={
              <Link to="/events" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                View all
              </Link>
            }
          />
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.events.length === 0 && (
              <p className="px-5 py-6 text-sm text-zinc-500">No events yet. Plan one from the Events page.</p>
            )}
            {data.events.map((event) => (
              <Link key={event.event_id} to={`/events/${event.event_id}`} className="block px-5 py-3.5 transition hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
                    <CalendarDays className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden />
                    {event.name}
                  </span>
                  <Badge value={event.status} />
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
              <Link to="/activity" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                Full history
              </Link>
            }
          />
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {data.activity.length === 0 && <p className="px-5 py-6 text-sm text-zinc-500">No activity recorded yet.</p>}
            {data.activity.map((entry) => (
              <div key={entry.activity_id} className="px-5 py-3">
                <p className="text-sm text-zinc-700 dark:text-zinc-300">{entry.description}</p>
                <p className="mt-0.5 text-xs text-zinc-400">{timeAgo(entry.timestamp)}</p>
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
              <div key={department.department_id} className="rounded-lg border border-zinc-200 p-3.5 dark:border-zinc-800">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{department.name}</p>
                  <span className="text-xs text-zinc-500">{department.member_count ?? 0} members</span>
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">Coordinator: {department.coordinator_name || "—"}</p>
                <ProgressBar completed={department.progress?.completed ?? 0} total={department.progress?.total ?? 0} className="mt-2.5" />
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
