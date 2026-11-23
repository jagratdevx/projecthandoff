import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeftRight, ArrowRight } from "lucide-react";
import { api } from "../api/client";
import type { Handover } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { Badge, Button, EmptyState, Input, PageHeader, SkeletonList, Tabs } from "../components/ui";
import { formatDate, timeAgo } from "../lib/format";

const STATUS_FILTERS = ["All", "pending", "clarification_requested", "accepted", "rejected", "cancelled"] as const;

export function Handovers() {
  const { user } = useAuth();
  const [direction, setDirection] = useState<"incoming" | "outgoing" | "team">("incoming");
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("All");
  const [query, setQuery] = useState("");

  const endpoint = useMemo(() => {
    const params = new URLSearchParams({ direction });
    if (statusFilter !== "All") params.set("status", statusFilter);
    if (query.trim()) params.set("task_id", "");
    return `/api/handovers?${params.toString()}`;
  }, [direction, statusFilter]);

  const { data, loading, error, reload } = useResource<Handover[]>(() => api(endpoint), [endpoint], 15000);

  const filtered = useMemo(() => {
    let list = data ?? [];
    if (query.trim()) {
      const needle = query.toLowerCase();
      list = list.filter(
        (h) =>
          (h.task_title ?? "").toLowerCase().includes(needle) ||
          (h.previous_owner_name ?? "").toLowerCase().includes(needle) ||
          (h.proposed_owner_name ?? "").toLowerCase().includes(needle),
      );
    }
    return list;
  }, [data, query]);

  return (
    <div>
      <PageHeader
        title="Handover inbox"
        subtitle="Responsibility transfers with full context"
      />

      <div className="mb-4 space-y-3">
        <Tabs
          tabs={[
            { id: "incoming", label: "Incoming", count: (data ?? []).filter((h) => h.proposed_owner_id === user?.user_id).length },
            { id: "outgoing", label: "Outgoing" },
            { id: "team", label: "All team" },
          ]}
          value={direction}
          onChange={setDirection}
        />
        <div className="flex flex-wrap items-center gap-2">
          {STATUS_FILTERS.map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium capitalize transition ${
                statusFilter === status
                  ? "bg-brand-600 text-white"
                  : "bg-stone-100 text-stone-600 hover:bg-stone-200 dark:bg-stone-800 dark:text-stone-300 dark:hover:bg-stone-700"
              }`}
            >
              {status.replace(/_/g, " ")}
            </button>
          ))}
          <Input
            placeholder="Search handovers…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full sm:ml-auto sm:max-w-xs"
            aria-label="Search handovers"
          />
        </div>
      </div>

      {loading && !data ? (
        <SkeletonList rows={3} />
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<ArrowLeftRight className="h-10 w-10" aria-hidden />}
          title="No handovers here"
          description={
            direction === "incoming"
              ? "When someone hands a task over to you, it appears here with the complete context."
              : "Handovers you request will show up here until they are resolved."
          }
          action={
            <Button variant="secondary" onClick={() => void reload()}>
              Refresh
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((handover) => (
            <Link key={handover.handover_id} to={`/handovers/${handover.handover_id}`} className="card-base block p-4 transition hover:border-brand-300 dark:hover:border-brand-700">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2 text-sm">
                  <span className="truncate font-medium text-stone-900 dark:text-stone-100">{handover.task_title || "Task handover"}</span>
                  <Badge value={handover.status} className="shrink-0" />
                </div>
                <span className="text-xs text-stone-400">sent {timeAgo(handover.created_at)}</span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-stone-600 dark:text-stone-300">
                <span className="font-medium">{handover.previous_owner_name}</span>
                <ArrowRight className="h-3.5 w-3.5 text-stone-400" aria-hidden />
                <span className="font-medium">{handover.proposed_owner_name}</span>
                {handover.deadline && <span className="text-xs text-stone-500">· target {formatDate(handover.deadline)}</span>}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
