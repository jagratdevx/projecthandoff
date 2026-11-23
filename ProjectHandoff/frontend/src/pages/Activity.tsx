import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, FileText, Handshake, History, ListPlus, RefreshCcw, UserPlus } from "lucide-react";
import { api } from "../api/client";
import type { Activity } from "../api/types";
import { useResource } from "../hooks/useResource";
import { Button, EmptyState, PageHeader, SkeletonList } from "../components/ui";import { timeAgo } from "../lib/format";

const ICONS: Record<string, typeof History> = {
  task: ListPlus,
  handover: Handshake,
  file: FileText,
  team: UserPlus,
  project: Bot,
  event: Bot,
  department: Bot,
  comment: History,
};

function iconFor(action: string) {
  const key = action.split(".")[0];
  const Icon = ICONS[key] ?? History;
  return <Icon className="h-4 w-4 shrink-0 text-stone-400" aria-hidden />;
}

const PAGE_SIZE = 40;

export function ActivityPage() {
  const { data, loading, error } = useResource<{ items: Activity[]; total: number }>(
    () => api(`/api/activity?limit=${PAGE_SIZE}&offset=0`),
    [],
    15000,
  );
  const [visible, setVisible] = useState(PAGE_SIZE);

  const items = useMemo(() => data?.items.slice(0, visible) ?? [], [data, visible]);

  return (
    <div>
      <PageHeader title="Activity" subtitle="Audit-style timeline of everything happening in your team" />

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
