import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Fetch + optional background polling (10–15s) with manual refresh.
 * Skips polling while the tab is hidden; never overlaps requests.
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

  const reload = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const data = await fetcherRef.current();
      setState({ data, loading: false, error: null });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Something went wrong";
      setState((prev) => ({ data: prev.data, loading: false, error: message }));
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!pollMs) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, pollMs);
    return () => window.clearInterval(interval);
  }, [pollMs, reload]);

  return { ...state, reload, setData: (value) => setState((prev) => ({ ...prev, data: typeof value === "function" ? (value as (d: T | null) => T | null)(prev.data) : value })) };
}
