import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";

/** Members of the current team, refreshed every 30s. */
export function useMembers(enabled = true): User[] {
  const [members, setMembers] = useState<User[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api<{ team: unknown; members: User[] }>("/api/teams/mine");
        if (!cancelled) setMembers(data.members ?? []);
      } catch {
        /* keep previous members */
      }
    };
    void load();
    const interval = window.setInterval(load, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [enabled]);

  return members;
}
