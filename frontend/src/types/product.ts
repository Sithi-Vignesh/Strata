export type User = { id: number; name: string; email: string };

export type Workspace = { id: number; name: string; kind: "PERSONAL" | "COLLABORATIVE" };

export type WorkspaceMember = { workspace_id: number; user_id: number; role: "OWNER" | "MEMBER"; name: string; email: string; account_state: string };
export type OwnershipTransfer = { workspace_id: number; owner_user_id: number; previous_owner_user_id: number };

export type Project = {
  id: number;
  created_by_user_id?: number;
  workspace_id: number;
  name: string;
  description: string | null;
};

export const TASK_STATUSES = ["TODO", "IN_PROGRESS", "DONE"] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];

export const TASK_PRIORITIES = ["LOW", "MEDIUM", "HIGH"] as const;
export type TaskPriority = (typeof TASK_PRIORITIES)[number];

export type Task = {
  id: number;
  project_id: number;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_user_id: number | null;
  due_date?: string | null;
};

export type AssignedTask = Task & { project_name: string; workspace_id: number; workspace_name: string; assignee_name?: string | null };
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type TaskSort = "id" | "updated_desc" | "due_asc" | "due_desc" | "title";
export type TaskQuery = { query?: string; status?: TaskStatus; priority?: TaskPriority; due_before?: string; due_after?: string; workspace_id?: number; project_id?: number; sort?: TaskSort; limit?: number; offset?: number };

export type Dashboard = {
  scope: "account" | "workspace"; workspace_id: number | null;
  workspace_count: number; project_count: number; task_count: number;
  assigned_to_me: number; overdue_count: number; upcoming_count: number; completed_count: number;
  status_counts: Record<TaskStatus, number>; priority_counts: Record<TaskPriority, number>;
};

export type TaskActivity = {
  id: number; task_id: number; project_id: number; workspace_id: number;
  actor_user_id: number; event_type: string; details: Record<string, unknown> | null; created_at: number;
};

export type Notification = {
  id: number; recipient_user_id: number; event_type: string; summary: string;
  workspace_id: number | null; project_id: number | null; task_id: number | null;
  created_at: number; is_read: boolean; dismissed_at: number | null;
};

export type CreateTaskInput = {
  title: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  assignee_user_id?: number | null;
  due_date?: string | null;
};

export type UpdateTaskInput = Partial<{
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_user_id: number | null;
  due_date: string | null;
  handoff_note: string | null;
}>;

export type Note = { id: number; task_id: number; author_user_id: number; content: string };

export type CreateNoteInput = { content: string };
export type UpdateNoteInput = { content: string };
