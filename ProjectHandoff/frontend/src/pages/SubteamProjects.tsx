import { Link, useParams } from "react-router-dom";
import { ChevronRight, FolderKanban } from "lucide-react";
import { api } from "../api/client";
import type { Project, Subteam, Task } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { formatDate, isOverdue } from "../lib/format";
import { Badge, Button, EmptyState, ErrorNote, PageHeader, ProgressBar, SkeletonList } from "../components/ui";

/** All projects scoped to one subteam, reached from Team → Subteams. */
export function SubteamProjects() {
  const { subteamId = "" } = useParams<{ subteamId: string }>();
  const { team } = useAuth();

  const { data: subteams } = useResource<Subteam[]>(
    () => (team ? api(`/api/teams/${encodeURIComponent(team.team_id)}/subteams`) : Promise.resolve([])),
    [team?.team_id],
    0,
  );
  const subteam = subteams?.find((item) => item.subteam_id === subteamId);
  const scopedUrl = `/api/projects?subteam_id=${encodeURIComponent(subteamId)}`;

  const { data: projects, loading, error, reload } = useResource<Project[]>(() => api(scopedUrl), [scopedUrl], 15000);
  const { data: tasks } = useResource<Task[]>(
    () => api(`/api/tasks?subteam_id=${encodeURIComponent(subteamId)}`),
    [subteamId],
    30000,
  );

  const progressByProject = new Map<string, { total: number; completed: number }>();
  for (const task of tasks ?? []) {
    if (!task.project_id) continue;
    const entry = progressByProject.get(task.project_id) ?? { total: 0, completed: 0 };
    entry.total += 1;
    if (task.status === "Completed") entry.completed += 1;
    progressByProject.set(task.project_id, entry);
  }

  return (
    <div>
      <nav aria-label="Breadcrumb" className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-stone-500 dark:text-stone-400">
        <Link to="/team" className="hover:text-brand-600 hover:underline dark:hover:text-brand-400">Team</Link>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        <Link to="/team" className="hover:text-brand-600 hover:underline dark:hover:text-brand-400">Subteams</Link>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        <Link to="/team" className="hover:text-brand-600 hover:underline dark:hover:text-brand-400">
          {subteam?.name ?? "Subteam"}
        </Link>
        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        <span className="font-medium text-stone-800 dark:text-stone-100">Projects</span>
      </nav>

      <PageHeader
        title={`${subteam?.name ?? "Subteam"} projects`}
        subtitle="Requirements and workstreams owned by this subteam"
      />

      {error ? (
        <div className="space-y-3">
          <ErrorNote message={error} />
          <Button variant="secondary" onClick={() => void reload()}>Try again</Button>
        </div>
      ) : loading && !projects ? (
        <SkeletonList rows={3} />
      ) : !projects?.length ? (
        <EmptyState
          icon={<FolderKanban className="h-10 w-10" aria-hidden />}
          title="No projects for this subteam yet"
          description="Projects assigned to this subteam will appear here with their requirements."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {projects.map((project) => {
            const progress = progressByProject.get(project.project_id) ?? { total: 0, completed: 0 };
            const overdue = isOverdue(project.deadline, project.status);
            return (
              <Link
                key={project.project_id}
                to={`/projects/${project.project_id}`}
                className="card-base block min-w-0 p-5 transition hover:border-brand-300 dark:hover:border-brand-700"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="line-clamp-2 break-words font-medium text-stone-900 dark:text-stone-50">{project.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-sm text-stone-500 dark:text-stone-400">
                      {project.description || "No description"}
                    </p>
                  </div>
                  <Badge value={project.status} className="shrink-0" />
                </div>
                <p className="mt-3 line-clamp-3 whitespace-pre-wrap break-words rounded-lg bg-stone-50 px-3 py-2 text-xs text-stone-600 dark:bg-stone-800/60 dark:text-stone-300">
                  <span className="font-semibold">Requirements: </span>
                  {project.requirements || "No requirements recorded"}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                  <Badge value={project.priority} className="shrink-0" />
                  <span>·</span>
                  <span className={`min-w-0 ${overdue ? "font-medium text-red-600 dark:text-red-400" : ""}`}>
                    {project.deadline
                      ? overdue ? `Overdue (was due ${formatDate(project.deadline)})` : `Due ${formatDate(project.deadline)}`
                      : "No deadline"}
                  </span>
                </div>
                <ProgressBar completed={progress.completed} total={progress.total} className="mt-3" />
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
