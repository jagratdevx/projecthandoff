export type Role = "owner" | "admin" | "council" | "teacher" | "coordinator" | "member";
export type SubteamRole = "coordinator" | "volunteer";
export type TaskStatus = "Not Started" | "In Progress" | "Blocked" | "Under Review" | "Completed";
export type Priority = "Low" | "Medium" | "High" | "Critical";
export type ProjectStatus = "Planning" | "Active" | "On Hold" | "Completed" | "Archived";
export type EventStatus = "Planning" | "Active" | "Completed" | "Cancelled";
export type HandoverStatus = "pending" | "clarification_requested" | "accepted" | "rejected" | "cancelled";

export interface User {
  user_id: string;
  name: string;
  email: string;
  role: Role;
  team_id: string;
  joined_at: string;
  status: "active" | "inactive";
  subteams?: Array<{ subteam_id: string; name: string; role: SubteamRole }>;
}

export interface Team {
  team_id: string;
  name: string;
  description: string;
  owner_id: string;
  created_at: string;
  status: string;
  drive_folder_id?: string;
  drive_folder_url?: string;
}

/** A user's membership in a team, including completed (archived) events. */
export interface TeamMembership {
  team_id: string;
  name: string;
  description: string;
  status: string;
  role: Role;
  state: "active" | "observer" | "removed";
  is_current: boolean;
  joined_at: string;
}

/** Archived-team overview returned by GET /api/archive/{team_id}/summary. */
export interface ArchiveSummary {
  team: Pick<Team, "team_id" | "name" | "description" | "status">;
  counts: Record<string, number>;
}

/** GET/POST/DELETE /api/teams/{id}/subteams */
export interface Subteam {
  subteam_id: string;
  team_id: string;
  name: string;
  description: string;
  folder_id: string;
  folder_url: string | null;
  created_at: string;
  my_role?: SubteamRole | "";
  member_count?: number;
  can_manage?: boolean;
}

export interface SubteamMember {
  subteam_id: string;
  user_id: string;
  role: SubteamRole;
  added_by: string;
  added_at: string;
  name?: string;
  email?: string;
}

/** GET /api/teams/{id}/drive/status */
export interface TeamDriveStatus {
  storage_mode: string;
  client_configured: boolean;
  connected: boolean;
  /** True when the team runs on the organizer's (host) Drive account rather than its own OAuth connection. */
  via_host?: boolean;
  account: string | null;
  folder: { id: string; url: string } | null;
}

export interface Project {
  project_id: string;
  name: string;
  description: string;
  owner_id: string;
  start_date: string;
  deadline: string;
  status: ProjectStatus;
  priority: Priority;
  created_at: string;
  updated_at: string;
  subteam_id: string;
  requirements: string;
  owner_name?: string;
  subteam_name?: string;
  /** Present on project detail; members assignable to this project's subteam. */
  assignable_members?: SubteamMember[];
  progress?: { total: number; completed: number };
}

/** A team user or a subteam membership enlisted as an assignable project member. */
export type ProjectMember = Pick<User, "user_id"> & { name?: string; email?: string };

export interface Task {
  task_id: string;
  project_id: string;
  event_id: string;
  department_id: string;
  title: string;
  description: string;
  assigned_to: string;
  created_by: string;
  priority: Priority;
  status: TaskStatus;
  deadline: string;
  version: string;
  created_at: string;
  updated_at: string;
  /** Derived from the task's project (or its legacy subteam) by the backend. */
  subteam_id: string;
  assignee_name?: string;
  task_title?: string;
}

export interface TaskStatusRequest {
  request_id: string;
  task_id: string;
  requested_by: string;
  requested_status: TaskStatus;
  note: string;
  status: "pending" | "approved" | "rejected";
  reviewed_by?: string;
  created_at: string;
  reviewed_at?: string;
  requested_by_name?: string;
  reviewed_by_name?: string;
}

export interface Comment {
  comment_id: string;
  task_id: string;
  user_id: string;
  comment: string;
  created_at: string;
}

export interface Handover {
  handover_id: string;
  task_id: string;
  previous_owner_id: string;
  proposed_owner_id: string;
  completed_work: string;
  remaining_work: string;
  current_state: string;
  blockers: string;
  next_actions: string;
  relevant_files: string;
  deadline: string;
  status: HandoverStatus;
  created_at: string;
  accepted_at: string;
  task_title?: string;
  previous_owner_name?: string;
  proposed_owner_name?: string;
  subteam_id?: string;
  subteam_name?: string;
  can_approve?: boolean;
}

export interface Event {
  event_id: string;
  name: string;
  description: string;
  start_date: string;
  end_date: string;
  owner_id: string;
  status: EventStatus;
  created_at: string;
  progress?: { total: number; completed: number };
}

export interface Department {
  department_id: string;
  event_id: string;
  name: string;
  coordinator_id: string;
  description: string;
  status: "Active" | "Archived";
  coordinator_name?: string;
  member_ids?: string[];
  member_count?: number;
  progress?: { total: number; completed: number };
}

export interface Activity {
  activity_id: string;
  team_id: string;
  project_id: string;
  task_id: string;
  user_id: string;
  action: string;
  description: string;
  timestamp: string;
  user_name?: string;
  subteam_id?: string;
  /** "main" or "subteam" — archived feeds separate the two sources. */
  source?: string;
}

export interface Attachment {
  attachment_id: string;
  task_id: string;
  project_id: string;
  drive_file_id: string;
  file_name: string;
  uploaded_by: string;
  uploaded_at: string;
}

export interface Invitation {
  invitation_id: string;
  team_id: string;
  email: string;
  role: Role;
  expires_at: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  token?: string;
  invite_url?: string;
  subteam_id?: string;
  subteam_role?: SubteamRole;
}

export interface DashboardData {
  stats: {
    active_projects: number;
    my_open_tasks: number;
    pending_handovers: number;
    upcoming_deadlines: number;
    overdue_tasks: number;
    team_size: number;
  };
  projects: Project[];
  my_tasks: Task[];
  upcoming_deadlines: Task[];
  incoming_handovers: Handover[];
  outgoing_handovers: Handover[];
  events: Event[];
  departments: Department[];
  activity: Activity[];
}
