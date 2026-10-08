export type User = { id: number; name: string; email: string };

export type Workspace = { id: number; name: string; kind: "PERSONAL" | "COLLABORATIVE" };

export type WorkspaceMember = { workspace_id: number; user_id: number; role: "OWNER" | "MEMBER"; name: string; email: string; account_state: string };
export type OwnershipTransfer = { workspace_id: number; owner_user_id: number; previous_owner_user_id: number };

export type Project = {
  id: number;
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
};

export type CreateTaskInput = {
  title: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  assignee_user_id?: number | null;
};

export type UpdateTaskInput = Partial<{
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_user_id: number | null;
}>;

export type Note = { id: number; task_id: number; author_user_id: number; content: string };

export type CreateNoteInput = { content: string };
export type UpdateNoteInput = { content: string };
