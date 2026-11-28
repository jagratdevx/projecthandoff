import { useAuth } from "../state/AuthContext";

/**
 * Completed events are archived and read-only on the server (writes return 409).
 * Pages use this to hide or disable controls that would issue a write.
 */
export function useReadOnly(): boolean {
  const { team } = useAuth();
  return !!team && team.status !== "active";
}
