import { requestJson } from "./strata";
import type { CreateNoteInput, CreateTaskInput, Note, Project, Task, UpdateNoteInput, UpdateTaskInput, User, Workspace, WorkspaceMember } from "../types/product";

export function getUser(userId: number): Promise<User> {
  return requestJson<User>(`/api/users/${userId}`);
}

export function listUserWorkspaces(userId: number): Promise<Workspace[]> {
  return requestJson<Workspace[]>(`/api/users/${userId}/workspaces`);
}

export function listWorkspaceProjects(workspaceId: number): Promise<Project[]> {
  return requestJson<Project[]>(`/api/workspaces/${workspaceId}/projects`);
}

export function listWorkspaceMembers(workspaceId: number): Promise<WorkspaceMember[]> {
  return requestJson<WorkspaceMember[]>(`/api/workspaces/${workspaceId}/members`);
}

export function listProjectTasks(projectId: number): Promise<Task[]> {
  return requestJson<Task[]>(`/api/projects/${projectId}/tasks`);
}

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
