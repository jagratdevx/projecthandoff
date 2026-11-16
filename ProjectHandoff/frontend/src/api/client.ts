import { useEffect, useState } from "react";
import type { Team, User } from "./types";

const TOKEN_KEY = "ph_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// ---------------------------------------------------------------------------
// Sync bus — the sync indicator subscribes to transport health.
// ---------------------------------------------------------------------------

export interface SyncState {
  lastSyncedAt: number | null;
  inflight: number;
  error: string | null;
}

let syncState: SyncState = { lastSyncedAt: null, inflight: 0, error: null };
const syncListeners = new Set<(s: SyncState) => void>();

function emitSync() {
  syncListeners.forEach((fn) => fn(syncState));
}

export function subscribeSync(fn: (s: SyncState) => void): () => void {
  syncListeners.add(fn);
  fn(syncState);
  return () => {
    syncListeners.delete(fn);
  };
}

function markInflightStart() {
  syncState = { ...syncState, inflight: syncState.inflight + 1 };
  emitSync();
}

function markInflightEnd() {
  syncState = { ...syncState, inflight: Math.max(0, syncState.inflight - 1) };
  emitSync();
}

function markSuccess() {
  syncState = { ...syncState, lastSyncedAt: Date.now(), error: null };
  emitSync();
}

function markError(error: string | null) {
  syncState = { ...syncState, error };
  emitSync();
}

// ---------------------------------------------------------------------------
// Request priority — what's on screen wins over background syncing.
//
// Browsers allow only a handful of parallel connections per host. Background
// work (polling, retries) must never occupy those slots while the user is
// actively navigating or acting, so background requests queue until user
// traffic goes quiet (or a short anti-starvation timeout fires).
// ---------------------------------------------------------------------------

export type RequestPriority = "user" | "background";

const BG_RESUME_IDLE_MS = 500; // quiet period after user traffic before queued background work starts
const BG_MAX_WAIT_MS = 4000; // background work never waits longer than this — no starvation

interface BackgroundEntry {
  started: boolean;
  run: () => void;
  timeout: number | null;
}

const backgroundQueue: BackgroundEntry[] = [];
let userRequests = 0;
let lastUserTrafficAt = 0;
let resumeTimer: number | null = null;

function flushBackgroundQueue() {
  if (userRequests > 0) return;
  if (Date.now() - lastUserTrafficAt < BG_RESUME_IDLE_MS) {
    // A user request just finished — give the next one a head start before
    // releasing background work.
    if (resumeTimer === null) {
      resumeTimer = window.setTimeout(() => {
        resumeTimer = null;
        flushBackgroundQueue();
      }, BG_RESUME_IDLE_MS);
    }
    return;
  }
  while (backgroundQueue.length > 0) {
    backgroundQueue.shift()!.run();
  }
}

function enqueueBackground(run: () => void) {
  const entry: BackgroundEntry = {
    started: false,
    run: () => {
      if (entry.started) return;
      entry.started = true;
      if (entry.timeout !== null) {
        window.clearTimeout(entry.timeout);
        entry.timeout = null;
      }
      run();
    },
    timeout: null,
  };
  entry.timeout = window.setTimeout(entry.run, BG_MAX_WAIT_MS);
  backgroundQueue.push(entry);
  flushBackgroundQueue();
}

function beginUserRequest(): () => void {
  userRequests += 1;
  lastUserTrafficAt = Date.now();
  return () => {
    userRequests = Math.max(0, userRequests - 1);
    lastUserTrafficAt = Date.now();
    flushBackgroundQueue();
  };
}

// Fetchers wrapped here are marked as background work for the duration of
// their (synchronous) api() calls — used by polling and retries.
let backgroundDepth = 0;

export function runBackground<T>(fn: () => Promise<T>): Promise<T> {
  backgroundDepth += 1;
  return Promise.resolve().then(fn).finally(() => {
    backgroundDepth -= 1;
  });
}

// ---------------------------------------------------------------------------
// HTTP client
// ---------------------------------------------------------------------------

const BASE_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  skipAuth?: boolean;
  /** "user" (default) runs immediately; "background" yields to user traffic. */
  priority?: RequestPriority;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = options.form ? "POST" : "GET", body, form, skipAuth } = options;
  const priority: RequestPriority = options.priority ?? (backgroundDepth > 0 ? "background" : "user");
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token && !skipAuth) headers["Authorization"] = `Bearer ${token}`;

  let payload: BodyInit | undefined;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  // Background requests (polls, retries) wait for the connection slots the
  // user's live screen is not using. Queued requests don't count as inflight,
  // so the sync indicator stays quiet about them.
  if (priority === "background") {
    await new Promise<void>((resolve) => enqueueBackground(resolve));
  }

  markInflightStart();
  let response: Response;
  let releaseUser: (() => void) | null = null;
  try {
    if (priority === "user") releaseUser = beginUserRequest();
    response = await fetch(`${BASE_URL}${path}`, { method, headers, body: payload });
  } catch {
    markError("Cannot reach the server — you appear to be offline");
    throw new ApiError("Cannot reach the server. Check your connection and try again.", 0);
  } finally {
    releaseUser?.();
    markInflightEnd();
  }

  if (response.status === 401 && !skipAuth && !path.startsWith("/api/auth")) {
    clearToken();
    markError(null);
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new ApiError("Session expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (data && typeof data.detail === "string") detail = data.detail;
    } catch {
      /* non-JSON error body */
    }
    if (response.status === 502 || response.status === 503) {
      markError(detail);
    }
    throw new ApiError(detail, response.status);
  }

  markSuccess();
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function downloadAttachment(attachmentId: string, fileName: string) {
  const response = await fetch(`${BASE_URL}/api/attachments/${attachmentId}/download`, {
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
  });
  if (!response.ok) throw new ApiError("Download failed", response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Me endpoint helpers
// ---------------------------------------------------------------------------

export function fetchMe(): Promise<{ user: User; team: Team | null }> {
  return api("/api/auth/me");
}

export function useMe(): { user: User | null; team: Team | null; loading: boolean } {
  const [state, setState] = useState<{ user: User | null; team: Team | null; loading: boolean }>({
    user: null,
    team: null,
    loading: true,
  });
  useEffect(() => {
    let cancelled = false;
    if (!getToken()) {
      setState({ user: null, team: null, loading: false });
      return;
    }
    fetchMe()
      .then((data) => {
        if (!cancelled) setState({ user: data.user, team: data.team, loading: false });
      })
      .catch(() => {
        if (!cancelled) setState({ user: null, team: null, loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
