import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { listProjectTasks, listUserWorkspaces, listWorkspaceMembers, listWorkspaceProjects } from "../api/product";
import type { Project, Task, User, Workspace, WorkspaceMember } from "../types/product";

type ProductState = { workspaces: Workspace[]; projects: Project[]; members: WorkspaceMember[]; memberUsers: Record<number, User>; tasks: Task[]; workspaceTasks: Record<number, Task[]>; selectedWorkspaceId: number | null; selectedProjectId: number | null; status: "loading" | "ready" | "error"; error: Error | null; };
type ProductContextValue = ProductState & { currentUser: User; selectWorkspace: (workspaceId: number) => void; selectProject: (projectId: number) => void; retry: () => void; refreshTasks: () => Promise<void>; refreshWorkspace: () => Promise<void>; };
const ProductContext = createContext<ProductContextValue | null>(null);
const initialState: ProductState = { workspaces: [], projects: [], members: [], memberUsers: {}, tasks: [], workspaceTasks: {}, selectedWorkspaceId: null, selectedProjectId: null, status: "loading", error: null };

export function ProductProvider({ children, user }: { children: ReactNode; user: User }) {
  const [state, setState] = useState<ProductState>(initialState);
  const requestVersion = useRef(0);
  const workspaceKey = `strata.user.${user.id}.selectedWorkspaceId`;
  const projectKey = `strata.user.${user.id}.selectedProjectId`;
  const loadWorkspace = useCallback(async (workspaceId: number, preferredProjectId?: number | null) => {
    const version = ++requestVersion.current;
    setState((current) => ({ ...current, status: "loading", error: null, selectedWorkspaceId: workspaceId, projects: [], members: [], memberUsers: {}, tasks: [], workspaceTasks: {}, selectedProjectId: null }));
    try {
      const [projects, members] = await Promise.all([listWorkspaceProjects(workspaceId), listWorkspaceMembers(workspaceId)]);
      if (version !== requestVersion.current) return;
      const taskLists = await Promise.all(projects.map(async (project) => [project.id, await listProjectTasks(project.id)] as const));
      if (version !== requestVersion.current) return;
      const workspaceTasks = Object.fromEntries(taskLists);
      const projectId = chooseId(projects, preferredProjectId ?? readStoredId(projectKey));
      if (projectId === null) { persistId(projectKey, null); setState((current) => ({ ...current, projects, members, memberUsers: userMap(members), workspaceTasks, selectedProjectId: null, tasks: [], status: "ready" })); return; }
      persistId(projectKey, projectId);
      setState((current) => ({ ...current, projects, members, memberUsers: userMap(members), workspaceTasks, selectedProjectId: projectId, tasks: workspaceTasks[projectId] ?? [], status: "ready" }));
    } catch (error) { if (version === requestVersion.current) setState((current) => ({ ...current, status: "error", error: asError(error) })); }
  }, [projectKey]);
  const initialize = useCallback(async () => {
    const version = ++requestVersion.current; setState(initialState);
    try {
      const workspaces = await listUserWorkspaces(user.id);
      if (version !== requestVersion.current) return;
      const workspaceId = chooseId(workspaces, readStoredId(workspaceKey));
      if (workspaceId === null) { persistId(workspaceKey, null); setState({ ...initialState, workspaces, status: "ready" }); return; }
      persistId(workspaceKey, workspaceId); setState((current) => ({ ...current, workspaces, selectedWorkspaceId: workspaceId })); await loadWorkspace(workspaceId);
    } catch (error) { if (version === requestVersion.current) setState((current) => ({ ...current, status: "error", error: asError(error) })); }
  }, [loadWorkspace, user.id, workspaceKey]);
  useEffect(() => { void initialize(); }, [initialize]);
  const selectWorkspace = useCallback((workspaceId: number) => { persistId(workspaceKey, workspaceId); void loadWorkspace(workspaceId, null); }, [loadWorkspace, workspaceKey]);
  const selectProject = useCallback((projectId: number) => { if (state.selectedWorkspaceId === null || !state.projects.some((project) => project.id === projectId)) return; persistId(projectKey, projectId); void loadWorkspace(state.selectedWorkspaceId, projectId); }, [loadWorkspace, projectKey, state.projects, state.selectedWorkspaceId]);
  const refreshTasks = useCallback(async () => { const projectId = state.selectedProjectId; if (projectId === null) return; const version = ++requestVersion.current; setState((current) => ({ ...current, status: "loading", error: null })); try { const tasks = await listProjectTasks(projectId); if (version === requestVersion.current) setState((current) => ({ ...current, tasks, workspaceTasks: { ...current.workspaceTasks, [projectId]: tasks }, status: "ready" })); } catch (error) { const taskError = asError(error); if (version === requestVersion.current) setState((current) => ({ ...current, status: "error", error: taskError })); throw taskError; } }, [state.selectedProjectId]);
  const refreshWorkspace = useCallback(async () => { await initialize(); }, [initialize]);
  const value = useMemo(() => ({ ...state, currentUser: user, selectWorkspace, selectProject, retry: initialize, refreshTasks, refreshWorkspace }), [state, user, selectWorkspace, selectProject, initialize, refreshTasks, refreshWorkspace]);
  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}
export function useProduct() { const value = useContext(ProductContext); if (value === null) throw new Error("useProduct must be used within ProductProvider."); return value; }
export function useOptionalProduct() { return useContext(ProductContext); }
function chooseId<T extends { id: number }>(items: T[], preferredId: number | null): number | null { return items.some((item) => item.id === preferredId) ? preferredId : (items[0]?.id ?? null); }
function userMap(members: WorkspaceMember[]): Record<number, User> { return Object.fromEntries(members.map((member) => [member.user_id, { id: member.user_id, name: member.name, email: member.email }])); }
function readStoredId(key: string): number | null { try { const value = window.localStorage.getItem(key); const id = value === null ? NaN : Number(value); return Number.isInteger(id) && id > 0 ? id : null; } catch { return null; } }
function persistId(key: string, id: number | null) { try { if (id === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, String(id)); } catch { /* optional */ } }
function asError(error: unknown): Error { return error instanceof Error ? error : new Error("Could not load product data."); }
