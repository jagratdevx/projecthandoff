import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, runBackground } from "../api/client";

interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

const RETRY_BASE_MS = 2500;
const RETRY_MAX_MS = 30000;

/**
 * Fetch + optional background polling (10–15s) with manual refresh.
 * Skips polling while the tab is hidden; never overlaps requests.
 *
 * A failed sync retries itself with growing backoff (bounded) — quick
 * blips self-heal without user action; the regular poll keeps ticking too.
 *
 * Priority model: the initial load and refreshes triggered by your actions
 * run as "user" requests and always get the connection slots first; the
 * periodic poll and the retry loop run as "background" and yield to
 * whatever is on screen (see api/client.ts). A refresh requested while a
 * background sync is still airborne is replayed right after it lands.
 */
export function useResource<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  pollMs = 0,
): ResourceState<T> & { reload: () => Promise<void>; setData: React.Dispatch<React.SetStateAction<T | null>> } {
  const [state, setState] = useState<ResourceState<T>>({ data: null, loading: true, error: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const inFlight = useRef(false);
  const pendingUserRefresh = useRef(false);
  const failures = useRef(0);
  const retryTimer = useRef<number | null>(null);
  const mounted = useRef(true);

  const load = useCallback(async (priority: "user" | "background") => {
    if (inFlight.current) {
      // Never drop a user-triggered refresh: replay it once the
      // in-flight sync settles (keeps results ordered, no overlap).
      if (priority === "user") pendingUserRefresh.current = true;
      return;
    }
    inFlight.current = true;
    try {
      const data = await (priority === "background" ? runBackground(fetcherRef.current) : fetcherRef.current());
      failures.current = 0;
      if (mounted.current) setState({ data, loading: false, error: null });
    } catch (error) {
      failures.current += 1;
      const message = error instanceof ApiError ? error.message : "Something went wrong";
      if (mounted.current) setState((prev) => ({ data: prev.data, loading: false, error: message }));
      // A failed sync retries itself: soon at first, gently capped later.
      // Poll-managed resources keep retrying; one-shot loads stop after a
      // few attempts so a dead endpoint doesn't nag forever.
      if (pollMs > 0 || failures.current <= 3) {
        if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
        retryTimer.current = window.setTimeout(
          () => {
            if (document.visibilityState === "visible") void load("background");
          },
          Math.min(RETRY_MAX_MS, RETRY_BASE_MS * failures.current),
        );
      }
    } finally {
      inFlight.current = false;
      if (pendingUserRefresh.current && priority !== "user") {
        pendingUserRefresh.current = false;
        void load("user");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollMs]);

  const reload = useCallback(() => load("user"), [load]);

  useEffect(() => {
    void load("user");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!pollMs) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void load("background");
    }, pollMs);
    return () => window.clearInterval(interval);
  }, [pollMs, load]);

  useEffect(
    () => () => {
      mounted.current = false;
      if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    },
    [],
  );

  return { ...state, reload, setData: (value) => setState((prev) => ({ ...prev, data: typeof value === "function" ? (value as (d: T | null) => T | null)(prev.data) : value })) };
}
