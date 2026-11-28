import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, clearToken, completeTeam as completeTeamApi, fetchMe, getToken, setToken, switchTeam as switchTeamApi } from "../api/client";
import type { Team, TeamMembership, User } from "../api/types";

interface AuthState {
  user: User | null;
  team: Team | null;
  subteams: NonNullable<User["subteams"]>;
  teams: TeamMembership[];
  canCreateTeam: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string, inviteToken?: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  switchTeam: (teamId: string) => Promise<void>;
  completeTeam: (teamId: string, force?: boolean) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [team, setTeam] = useState<Team | null>(null);
  const [subteams, setSubteams] = useState<NonNullable<User["subteams"]>>([]);
  const [teams, setTeams] = useState<TeamMembership[]>([]);
  const [canCreateTeam, setCanCreateTeam] = useState(false);
  const [loading, setLoading] = useState<boolean>(!!getToken());

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setTeam(null);
      setSubteams([]);
      setTeams([]);
      setCanCreateTeam(false);
      return;
    }
    try {
      const data = await fetchMe();
      setUser(data.user);
      setTeam(data.team);
      setSubteams(data.subteams ?? []);
      setTeams(data.teams ?? []);
      setCanCreateTeam(!!data.can_create_team);
    } catch {
      setUser(null);
      setTeam(null);
      setSubteams([]);
      setTeams([]);
      setCanCreateTeam(false);
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
    setSubteams([]);
    setTeams([]);
    setCanCreateTeam(false);
  }, []);

  const switchTeam = useCallback(
    async (teamId: string) => {
      await switchTeamApi(teamId);
      await refresh();
    },
    [refresh],
  );

  const completeTeam = useCallback(
    async (teamId: string, force = false) => {
      await completeTeamApi(teamId, force);
      await refresh();
    },
    [refresh],
  );

  const value = useMemo(
    () => ({
      user,
      team,
      subteams,
      teams,
      canCreateTeam,
      loading,
      login,
      register,
      logout,
      refresh,
      switchTeam,
      completeTeam,
    }),
    [user, team, subteams, teams, canCreateTeam, loading, login, register, logout, refresh, switchTeam, completeTeam],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
