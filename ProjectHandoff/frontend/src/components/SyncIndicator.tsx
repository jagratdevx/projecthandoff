import { useEffect, useRef, useState } from "react";
import { Check, CloudOff, Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { subscribeSync } from "../api/client";
import { formatTime } from "../lib/format";

/**
 * Transport-health indicator.
 *
 * Deliberately quiet: quick request bursts (navigating the app) show nothing
 * at all. Only requests that linger become visible ("Syncing…"), and a sync
 * that drags on turns into "Slow connection" — problems, not activity, are
 * what this indicator is for.
 */
export function SyncIndicator({ onRefresh }: { onRefresh?: () => void }) {
  const [state, setState] = useState({ lastSyncedAt: null as number | null, inflight: 0, error: null as string | null });
  const busyStart = useRef<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => subscribeSync(setState), []);

  // Track when the current busy period started.
  useEffect(() => {
    if (state.inflight > 0) {
      if (busyStart.current === null) busyStart.current = Date.now();
      const tick = window.setInterval(() => setNow(Date.now()), 1000);
      return () => window.clearInterval(tick);
    }
    busyStart.current = null;
    setNow(Date.now());
  }, [state.inflight]);

  const busyMs = busyStart.current !== null ? now - busyStart.current : 0;

  let icon: React.ReactNode;
  let label: string;
  let color = "text-stone-500 dark:text-stone-400";

  if (state.inflight > 0 && busyMs > 8000) {
    icon = <TriangleAlert className="h-3.5 w-3.5" aria-hidden />;
    label = "Slow connection — still syncing…";
    color = "text-amber-500";
  } else if (state.inflight > 0 && busyMs > 1500) {
    icon = <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />;
    label = "Syncing…";
    color = "text-brand-500";
  } else if (state.inflight > 0) {
    // Brief traffic (page navigation, quick actions): stay quiet.
    icon = <Check className="h-3.5 w-3.5" aria-hidden />;
    label = `Synced ${formatTime(state.lastSyncedAt)}`;
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
          className="rounded-md p-1.5 text-stone-500 transition hover:bg-stone-100 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-stone-100"
          title="Refresh now"
          aria-label="Refresh data now"
        >
          <RefreshCw className="h-4 w-4" aria-hidden />
        </button>
      )}
    </div>
  );
}
