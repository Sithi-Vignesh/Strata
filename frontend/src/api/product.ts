import { requestJson } from "./strata";
import type { AssignedTask, CreateNoteInput, CreateTaskInput, Dashboard, Note, Notification, OwnershipTransfer, Page, Project, Task, TaskActivity, TaskQuery, UpdateNoteInput, UpdateTaskInput, User, Workspace, WorkspaceMember } from "../types/product";

export type LoginInput = { email: string; password: string };
export type RegisterInput = { name: string; email: string; password: string };

export function getCurrentUser(): Promise<User> { return requestJson<User>("/api/auth/me"); }
export function login(input: LoginInput): Promise<User> { return requestJson<User>("/api/auth/login", jsonRequest("POST", input)); }
export function register(input: RegisterInput): Promise<User> { return requestJson<User>("/api/auth/register", jsonRequest("POST", input)); }
export function logout(): Promise<void> { return requestJson<void>("/api/auth/logout", { method: "POST" }); }

export function getUser(userId: number): Promise<User> {
  return requestJson<User>(`/api/users/${userId}`);
}

export function listUserWorkspaces(userId: number): Promise<Workspace[]> {
  return requestJson<Workspace[]>(`/api/users/${userId}/workspaces`);
}
export function createWorkspace(name: string): Promise<Workspace> { return requestJson<Workspace>("/api/workspaces", jsonRequest("POST", { name })); }

export function updateWorkspace(workspaceId: number, name: string): Promise<Workspace> { return requestJson<Workspace>(`/api/workspaces/${workspaceId}`, jsonRequest("PATCH", { name })); }
export function deleteWorkspace(workspaceId: number): Promise<void> { return requestJson<void>(`/api/workspaces/${workspaceId}`, { method: "DELETE" }); }
export function createProject(workspaceId: number, input: { name: string; description: string | null }): Promise<Project> { return requestJson<Project>(`/api/workspaces/${workspaceId}/projects`, jsonRequest("POST", input)); }
export function updateProject(projectId: number, input: { name?: string; description?: string | null }): Promise<Project> { return requestJson<Project>(`/api/projects/${projectId}`, jsonRequest("PATCH", input)); }
export function deleteProject(projectId: number): Promise<void> { return requestJson<void>(`/api/projects/${projectId}`, { method: "DELETE" }); }

export function listWorkspaceProjects(workspaceId: number): Promise<Project[]> {
  return requestJson<Project[]>(`/api/workspaces/${workspaceId}/projects`);
}

export function listWorkspaceMembers(workspaceId: number): Promise<WorkspaceMember[]> {
  return requestJson<WorkspaceMember[]>(`/api/workspaces/${workspaceId}/members`);
}
export function addWorkspaceMember(workspaceId: number, email: string): Promise<WorkspaceMember> { return requestJson<WorkspaceMember>(`/api/workspaces/${workspaceId}/members`, jsonRequest("POST", { email })); }
export function removeWorkspaceMember(workspaceId: number, userId: number): Promise<void> { return requestJson<void>(`/api/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" }); }
export function transferWorkspaceOwnership(workspaceId: number, userId: number): Promise<OwnershipTransfer> { return requestJson<OwnershipTransfer>(`/api/workspaces/${workspaceId}/transfer-ownership`, jsonRequest("POST", { new_owner_user_id: userId })); }

export function listProjectTasks(projectId: number, query?: TaskQuery): Promise<Task[]> {
  return requestJson<Task[]>(`/api/projects/${projectId}/tasks${queryString(query)}`);
}

export function listMyTasks(query?: TaskQuery): Promise<Page<AssignedTask>> { return requestJson<Page<AssignedTask>>(`/api/my/tasks${queryString(query)}`); }
export function listAllTasks(query?: TaskQuery): Promise<Page<AssignedTask>> { return requestJson<Page<AssignedTask>>(`/api/tasks${queryString(query)}`); }
export function getCommonDashboard(): Promise<Dashboard> { return requestJson<Dashboard>("/api/dashboard"); }
export function getWorkspaceDashboard(workspaceId: number): Promise<Dashboard> { return requestJson<Dashboard>(`/api/workspaces/${workspaceId}/dashboard`); }
export function listTaskActivity(taskId: number, limit = 50, offset = 0): Promise<Page<TaskActivity>> { return requestJson<Page<TaskActivity>>(`/api/tasks/${taskId}/activity?limit=${limit}&offset=${offset}`); }
export function listNotifications(options?: { unread_only?: boolean; limit?: number; offset?: number }): Promise<Page<Notification>> { return requestJson<Page<Notification>>(`/api/notifications${queryString(options)}`); }
export function getUnreadNotificationCount(): Promise<{ unread_count: number }> { return requestJson<{ unread_count: number }>("/api/notifications/unread-count"); }
export function setNotificationRead(notificationId: number, isRead: boolean): Promise<Notification> { return requestJson<Notification>(`/api/notifications/${notificationId}`, jsonRequest("PATCH", { is_read: isRead })); }
export function markAllNotificationsRead(): Promise<{ updated: number }> { return requestJson<{ updated: number }>("/api/notifications/mark-all-read", { method: "POST" }); }
export function dismissNotification(notificationId: number): Promise<void> { return requestJson<void>(`/api/notifications/${notificationId}`, { method: "DELETE" }); }

export function createTask(projectId: number, input: CreateTaskInput): Promise<Task> {
  return requestJson<Task>(`/api/projects/${projectId}/tasks`, jsonRequest("POST", input));
}

export function updateTask(taskId: number, input: UpdateTaskInput): Promise<Task> {
  return requestJson<Task>(`/api/tasks/${taskId}`, jsonRequest("PATCH", input));
}

export function deleteTask(taskId: number): Promise<void> {
  return requestJson<void>(`/api/tasks/${taskId}`, { method: "DELETE" });
}

export function listTaskNotes(taskId: number): Promise<Note[]> { return requestJson<Note[]>(`/api/tasks/${taskId}/notes`); }
export function createNote(taskId: number, input: CreateNoteInput): Promise<Note> { return requestJson<Note>(`/api/tasks/${taskId}/notes`, jsonRequest("POST", input)); }
export function updateNote(noteId: number, input: UpdateNoteInput): Promise<Note> { return requestJson<Note>(`/api/notes/${noteId}`, jsonRequest("PATCH", input)); }
export function deleteNote(noteId: number): Promise<void> { return requestJson<void>(`/api/notes/${noteId}`, { method: "DELETE" }); }

function jsonRequest(method: "POST" | "PATCH", body: object): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function queryString(values?: object): string {
  if (!values) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  const query = params.toString();
  return query ? `?${query}` : "";
}
