import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, FileText, Handshake, History, ListPlus, RefreshCcw, UserPlus, Users } from "lucide-react";
import { api } from "../api/client";
import type { Activity, Subteam } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { Button, EmptyState, PageHeader, Select, SkeletonList } from "../components/ui";
import { timeAgo } from "../lib/format";

const ICONS: Record<string, typeof History> = {
  task: ListPlus,
  handover: Handshake,
  file: FileText,
  team: UserPlus,
  project: Bot,
  event: Bot,
  department: Bot,
  subteam: Users,
  comment: History,
};

function iconFor(action: string) {
  const key = action.split(".")[0];
  const Icon = ICONS[key] ?? History;
  return <Icon className="h-4 w-4 shrink-0 text-stone-400" aria-hidden />;
}

const PAGE_SIZE = 40;

export function ActivityPage() {
  const { team } = useAuth();
  const [params, setParams] = useSearchParams();
  const subteamId = params.get("subteam_id") ?? "";

  const { data: subteams } = useResource<Subteam[]>(
    () => (team ? api(`/api/teams/${team.team_id}/subteams`) : Promise.resolve([])),
    [team?.team_id],
    0,
  );

  const { data, loading, error } = useResource<{ items: Activity[]; total: number }>(
    () => {
      const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: "0" });
      if (subteamId) query.set("subteam_id", subteamId);
      return api(`/api/activity?${query.toString()}`);
    },
    [subteamId],
    15000,
  );
  const [visible, setVisible] = useState(PAGE_SIZE);

  useEffect(() => {
    setVisible(PAGE_SIZE);
  }, [subteamId]);

  const changeScope = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set("subteam_id", value);
    else next.delete("subteam_id");
    setParams(next);
  };

  const items = useMemo(() => data?.items.slice(0, visible) ?? [], [data, visible]);

  return (
    <div>
      <PageHeader
        title="Activity"
        subtitle="Audit-style timeline of everything happening in your team"
        actions={
          <Select
            value={subteamId}
            onChange={(e) => changeScope(e.target.value)}
            className="w-full sm:w-48"
            aria-label="Activity scope"
          >
            <option value="">Main team</option>
            {(subteams ?? []).map((subteam) => (
              <option key={subteam.subteam_id} value={subteam.subteam_id}>
                {subteam.name}
              </option>
            ))}
          </Select>
        }
      />

      {loading && !data ? (
        <SkeletonList rows={6} />
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<History className="h-10 w-10" aria-hidden />}
          title="No activity yet"
          description="Task updates, handovers, uploads and team changes will appear here."
        />
      ) : (
        <div className="card-base divide-y divide-stone-100 dark:divide-stone-800">
          {items.map((entry) => (
            <div key={entry.activity_id} className="flex items-start gap-3 px-5 py-3.5">
              <span className="mt-1">{iconFor(entry.action)}</span>
              <div className="min-w-0 flex-1">
                <p className="break-words text-sm text-stone-700 [overflow-wrap:anywhere] dark:text-stone-300">
                  {entry.task_id ? (
                    <Link to={`/tasks/${entry.task_id}`} className="hover:underline">
                      {entry.description}
                    </Link>
                  ) : (
                    entry.description
                  )}
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-stone-400">
                  <code className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-mono dark:bg-stone-800">{entry.action}</code>
                  <span>{timeAgo(entry.timestamp)}</span>
                </p>
              </div>
            </div>
          ))}
          {visible < (data?.total ?? 0) && (
            <div className="p-4 text-center">
              <Button variant="secondary" onClick={() => setVisible((v) => v + PAGE_SIZE)}>
                <RefreshCcw className="h-4 w-4" aria-hidden /> Load older entries
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
