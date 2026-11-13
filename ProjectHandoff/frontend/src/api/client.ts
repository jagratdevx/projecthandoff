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
// HTTP client
// ---------------------------------------------------------------------------

const BASE_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  skipAuth?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = options.form ? "POST" : "GET", body, form, skipAuth } = options;
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

  markInflightStart();
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { method, headers, body: payload });
  } catch {
    markInflightEnd();
    markError("Cannot reach the server — you appear to be offline");
    throw new ApiError("Cannot reach the server. Check your connection and try again.", 0);
  }
  markInflightEnd();

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
