import { requestJson } from "./strata";
import type { Project, Task, User, Workspace, WorkspaceMember } from "../types/product";

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
