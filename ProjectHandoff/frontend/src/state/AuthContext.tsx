import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, clearToken, fetchMe, getToken, setToken } from "../api/client";
import type { Team, User } from "../api/types";

interface AuthState {
  user: User | null;
  team: Team | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string, inviteToken?: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState<boolean>(!!getToken());

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setTeam(null);
      return;
    }
    try {
      const data = await fetchMe();
      setUser(data.user);
      setTeam(data.team);
    } catch {
      setUser(null);
      setTeam(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await api<{ token: string; user: User }>("/api/auth/login", {
        method: "POST",
        body: { email, password },
        skipAuth: true,
      });
      setToken(data.token);
      setUser(data.user);
      await refresh();
    },
    [refresh],
  );

  const register = useCallback(
    async (name: string, email: string, password: string, inviteToken?: string) => {
      const data = await api<{ token: string; user: User }>("/api/auth/register", {
        method: "POST",
        body: { name, email, password, invite_token: inviteToken ?? "" },
        skipAuth: true,
      });
      setToken(data.token);
      setUser(data.user);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    setTeam(null);
  }, []);

  const value = useMemo(
    () => ({ user, team, loading, login, register, logout, refresh }),
    [user, team, loading, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
