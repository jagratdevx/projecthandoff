import { api } from "../api/client";
import type { SubteamMember } from "../api/types";
import { useResource } from "./useResource";
import { useAuth } from "../state/AuthContext";

export interface SubteamMembersState {
  members: SubteamMember[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

/**
 * Members of one subteam, including their name and email.
 * Pass a null/empty id to skip the request (e.g. no project selected yet).
 */
export function useSubteamMembers(subteamId: string | null | undefined): SubteamMembersState {
  const { team } = useAuth();
  const id = (subteamId ?? "").trim();
  const { data, loading, error, reload } = useResource<SubteamMember[]>(
    () =>
      id && team
        ? api<SubteamMember[]>(
            `/api/teams/${encodeURIComponent(team.team_id)}/subteams/${encodeURIComponent(id)}/members`,
          )
        : Promise.resolve([]),
    [team?.team_id, id],
    0,
  );
  return { members: data ?? [], loading, error, reload };
}
