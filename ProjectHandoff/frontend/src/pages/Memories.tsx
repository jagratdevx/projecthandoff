import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Archive, History, RefreshCcw } from "lucide-react";
import { api } from "../api/client";
import type { Activity, ArchiveSummary, Subteam, TeamMembership } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  PageHeader,
  Select,
  SkeletonList,
} from "../components/ui";
import { formatDate, timeAgo } from "../lib/format";

const PAGE_SIZE = 50;

export function Memories() {
  const { switchTeam } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [selectedId, setSelectedId] = useState("");
  const [scope, setScope] = useState("main");
  const [switching, setSwitching] = useState(false);

  const { data: memories, loading, error, reload } = useResource<TeamMembership[]>(
    () => api("/api/teams/memories"),
    [],
    60000,
  );
  const selected = memories?.find((item) => item.team_id === selectedId) ?? null;

  // Archived subteam names are best-effort: the teams endpoint only lists a
  // team's subteams when that team is current. IDs seen in the log fill the gaps.
  const { data: subteams } = useResource<Subteam[]>(
    () => (selectedId ? api<Subteam[]>(`/api/teams/${selectedId}/subteams`).catch(() => []) : Promise.resolve([])),
    [selectedId],
    0,
  );
  const { data: summary } = useResource<ArchiveSummary | null>(
    () => (selectedId ? api(`/api/archive/${selectedId}/summary`) : Promise.resolve(null)),
    [selectedId],
    0,
  );
  const { data: mainActivity } = useResource<{ items: Activity[]; total: number } | null>(
    () =>
      selectedId
        ? api(`/api/archive/${selectedId}/activity?limit=${PAGE_SIZE}&offset=0`)
        : Promise.resolve(null),
    [selectedId],
    60000,
  );
  const { data: subteamActivity } = useResource<{ items: Activity[]; total: number } | null>(
    () =>
      selectedId && scope !== "main"
        ? api(`/api/archive/${selectedId}/subteams/${encodeURIComponent(scope)}/activity?limit=${PAGE_SIZE}&offset=0`)
        : Promise.resolve(null),
    [selectedId, scope],
    60000,
  );

  useEffect(() => {
    setScope("main");
  }, [selectedId]);

  const subteamOptions = useMemo(() => {
    const found = new Map<string, string>();
    (subteams ?? []).forEach((subteam) => found.set(subteam.subteam_id, subteam.name));
    (mainActivity?.items ?? []).forEach((entry) => {
      if (entry.subteam_id && !found.has(entry.subteam_id)) found.set(entry.subteam_id, "Subteam activity");
    });
    return Array.from(found, ([id, name]) => ({ id, name }));
  }, [subteams, mainActivity]);

  const items = (scope === "main" ? mainActivity?.items : subteamActivity?.items) ?? [];

  const openMemory = async () => {
    if (!selected) return;
    setSwitching(true);
    try {
      await switchTeam(selected.team_id);
      toast.push("success", `Opened ${selected.name} as a read-only memory`);
      navigate("/team");
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Could not open this memory");
    } finally {
      setSwitching(false);
    }
  };

  if (selected) {
    return (
      <div>
        <button
          onClick={() => setSelectedId("")}
          className="mb-3 text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-100"
        >
          ← All memories
        </button>
        <PageHeader
          title={selected.name}
          subtitle={`Archived event · your role: ${selected.role} · joined ${formatDate(selected.joined_at)}`}
          actions={
            <Button variant="secondary" onClick={() => void openMemory()} loading={switching}>
              Open read-only
            </Button>
          }
        />

        <div className="mb-6 flex items-start gap-3 rounded-xl border border-stone-200 bg-white/70 px-4 py-3 dark:border-stone-800 dark:bg-stone-900/50">
          <Archive className="mt-0.5 h-4 w-4 shrink-0 text-stone-400" aria-hidden />
          <p className="text-sm text-stone-600 dark:text-stone-300">
            This event is complete. Everything below is a snapshot — nothing here can be edited.
          </p>
        </div>

        <Card className="mb-6">
          <CardHeader title="Summary" />
          <div className="grid gap-3 px-5 py-4 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(summary?.counts ?? {}).map(([key, count]) => (
              <div key={key} className="rounded-xl bg-stone-50 px-3 py-2.5 dark:bg-stone-800/60">
                <p className="text-lg font-semibold tabular-nums text-stone-900 dark:text-stone-100">{count}</p>
                <p className="text-[11px] capitalize text-stone-500 dark:text-stone-400">{key.replace(/_/g, " ")}</p>
              </div>
            ))}
            {!summary && <SkeletonList rows={1} />}
          </div>
          {summary?.team.description && (
            <p className="border-t border-stone-100 px-5 py-3 text-sm text-stone-600 dark:border-stone-800 dark:text-stone-300">
              {summary.team.description}
            </p>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Activity log"
            action={
              <Select value={scope} onChange={(e) => setScope(e.target.value)} className="w-full sm:w-56" aria-label="Archived activity scope">
                <option value="main">Main team log</option>
                {subteamOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </Select>
            }
          />
          {items.length === 0 ? (
            <p className="px-5 py-6 text-sm text-stone-500">No activity recorded for this scope.</p>
          ) : (
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {items.map((entry) => (
                <div key={entry.activity_id} className="flex items-start gap-3 px-5 py-3.5">
                  <History className="mt-0.5 h-4 w-4 shrink-0 text-stone-400" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-sm text-stone-700 [overflow-wrap:anywhere] dark:text-stone-300">
                      {entry.description || entry.action}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-stone-400">
                      <code className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-mono dark:bg-stone-800">{entry.action}</code>
                      {entry.user_name && <span>{entry.user_name}</span>}
                      <span>{timeAgo(entry.timestamp)}</span>
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Memories" subtitle="Completed events, kept read-only with their full history" />
      {loading && !memories ? (
        <SkeletonList rows={3} />
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : !memories?.length ? (
        <EmptyState
          icon={<Archive className="h-10 w-10" aria-hidden />}
          title="No memories yet"
          description="When an event is completed, it moves here with its log intact for reference."
          action={
            <Button variant="secondary" onClick={() => void reload()}>
              <RefreshCcw className="h-4 w-4" aria-hidden /> Refresh
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {memories.map((memory) => (
            <Card key={memory.team_id} className="flex flex-wrap items-center justify-between gap-3 p-5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold text-stone-900 dark:text-stone-100">{memory.name}</p>
                  <Badge value={memory.status} />
                  {memory.is_current && <Badge value="current" />}
                </div>
                <p className="mt-1 break-words text-xs text-stone-500">{memory.description || "No description"}</p>
                <p className="mt-1 text-xs text-stone-400">
                  Your role: {memory.role} · joined {formatDate(memory.joined_at)}
                </p>
              </div>
              <Button variant="secondary" onClick={() => setSelectedId(memory.team_id)}>
                Open
              </Button>
            </Card>
          ))}
          <p className="text-xs text-stone-500">
            Need a fresh event? Switch to an active team in the sidebar, or <Link to="/team" className="link-accent">manage teams</Link>.
          </p>
        </div>
      )}
    </div>
  );
}
