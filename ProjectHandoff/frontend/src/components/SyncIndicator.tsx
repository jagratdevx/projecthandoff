import { useEffect, useState } from "react";
import { Check, CloudOff, Loader2, RefreshCw } from "lucide-react";
import { subscribeSync } from "../api/client";
import { formatTime } from "../lib/format";

export function SyncIndicator({ onRefresh }: { onRefresh?: () => void }) {
  const [state, setState] = useState({ lastSyncedAt: null as number | null, inflight: 0, error: null as string | null });

  useEffect(() => subscribeSync(setState), []);

  let icon: React.ReactNode;
  let label: string;
  let color = "text-zinc-500 dark:text-zinc-400";

  if (state.inflight > 0) {
    icon = <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />;
    label = "Syncing…";
    color = "text-indigo-500";
  } else if (state.error) {
    icon = <CloudOff className="h-3.5 w-3.5" aria-hidden />;
    label = state.error.length > 42 ? `${state.error.slice(0, 42)}…` : state.error;
    color = "text-red-500";
  } else {
    icon = <Check className="h-3.5 w-3.5" aria-hidden />;
    label = `Synced ${formatTime(state.lastSyncedAt)}`;
  }

  return (
    <div className="flex items-center gap-2.5">
      <span
        className={`hidden items-center gap-1.5 text-xs sm:inline-flex ${color}`}
        title={state.error ?? `Last synchronized with the server at ${formatTime(state.lastSyncedAt)}`}
      >
        {icon}
        {label}
      </span>
      {onRefresh && (
        <button
          onClick={onRefresh}
          className="rounded-md p-1.5 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          title="Refresh now"
          aria-label="Refresh data now"
        >
          <RefreshCw className="h-4 w-4" aria-hidden />
        </button>
      )}
    </div>
  );
}
