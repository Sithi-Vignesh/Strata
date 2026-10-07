import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getUser, listProjectTasks, listUserWorkspaces, listWorkspaceMembers, listWorkspaceProjects } from "../api/product";
import type { Project, Task, User, Workspace, WorkspaceMember } from "../types/product";

/** Temporary deterministic product identity until authentication is implemented. */
export const CURRENT_USER_ID = 1;
const WORKSPACE_KEY = "strata.selectedWorkspaceId";
const PROJECT_KEY = "strata.selectedProjectId";

type ProductState = {
  currentUser: User | null;
  workspaces: Workspace[];
  projects: Project[];
  members: WorkspaceMember[];
  memberUsers: Record<number, User>;
  tasks: Task[];
  selectedWorkspaceId: number | null;
  selectedProjectId: number | null;
  status: "loading" | "ready" | "error";
  error: Error | null;
};

type ProductContextValue = ProductState & {
  selectWorkspace: (workspaceId: number) => void;
  selectProject: (projectId: number) => void;
  retry: () => void;
  refreshTasks: () => Promise<void>;
};

const ProductContext = createContext<ProductContextValue | null>(null);
const initialState: ProductState = {
  currentUser: null, workspaces: [], projects: [], members: [], memberUsers: {}, tasks: [],
  selectedWorkspaceId: null, selectedProjectId: null, status: "loading", error: null,
};

export function ProductProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ProductState>(initialState);
  const requestVersion = useRef(0);

  const loadWorkspace = useCallback(async (workspaceId: number, preferredProjectId?: number | null) => {
    const version = ++requestVersion.current;
    setState((current) => ({ ...current, status: "loading", error: null, selectedWorkspaceId: workspaceId, projects: [], members: [], memberUsers: {}, tasks: [], selectedProjectId: null }));
    try {
      const [projects, members] = await Promise.all([listWorkspaceProjects(workspaceId), listWorkspaceMembers(workspaceId)]);
      const users = await Promise.all(members.map((member) => getUser(member.user_id)));
      if (version !== requestVersion.current) return;
      const projectId = chooseId(projects, preferredProjectId ?? readStoredId(PROJECT_KEY));
      if (projectId === null) {
        persistId(PROJECT_KEY, null);
        setState((current) => ({ ...current, projects, members, memberUsers: userMap(users), selectedProjectId: null, tasks: [], status: "ready" }));
        return;
      }
      persistId(PROJECT_KEY, projectId);
      const tasks = await listProjectTasks(projectId);
      if (version !== requestVersion.current) return;
      setState((current) => ({ ...current, projects, members, memberUsers: userMap(users), selectedProjectId: projectId, tasks, status: "ready" }));
    } catch (error) {
      if (version === requestVersion.current) setState((current) => ({ ...current, status: "error", error: asError(error) }));
    }
  }, []);

  const initialize = useCallback(async () => {
    const version = ++requestVersion.current;
    setState(initialState);
    try {
      const [currentUser, workspaces] = await Promise.all([getUser(CURRENT_USER_ID), listUserWorkspaces(CURRENT_USER_ID)]);
      if (version !== requestVersion.current) return;
      const workspaceId = chooseId(workspaces, readStoredId(WORKSPACE_KEY));
      if (workspaceId === null) {
        persistId(WORKSPACE_KEY, null);
        setState({ ...initialState, currentUser, workspaces, status: "ready" });
        return;
      }
      persistId(WORKSPACE_KEY, workspaceId);
      setState((current) => ({ ...current, currentUser, workspaces, selectedWorkspaceId: workspaceId }));
      await loadWorkspace(workspaceId);
    } catch (error) {
      if (version === requestVersion.current) setState((current) => ({ ...current, status: "error", error: asError(error) }));
    }
  }, [loadWorkspace]);

  useEffect(() => { void initialize(); }, [initialize]);

  const selectWorkspace = useCallback((workspaceId: number) => {
    persistId(WORKSPACE_KEY, workspaceId);
    void loadWorkspace(workspaceId, null);
  }, [loadWorkspace]);

  const selectProject = useCallback((projectId: number) => {
    if (state.selectedWorkspaceId === null || !state.projects.some((project) => project.id === projectId)) return;
    persistId(PROJECT_KEY, projectId);
    void loadWorkspace(state.selectedWorkspaceId, projectId);
  }, [loadWorkspace, state.projects, state.selectedWorkspaceId]);

  const refreshTasks = useCallback(async () => {
    if (state.selectedProjectId === null) return;
    const version = ++requestVersion.current;
    setState((current) => ({ ...current, status: "loading", error: null }));
    try {
      const tasks = await listProjectTasks(state.selectedProjectId);
      if (version === requestVersion.current) setState((current) => ({ ...current, tasks, status: "ready" }));
    } catch (error) {
      const taskError = asError(error);
      if (version === requestVersion.current) setState((current) => ({ ...current, status: "error", error: taskError }));
      throw taskError;
    }
  }, [state.selectedProjectId]);

  const value = useMemo(() => ({ ...state, selectWorkspace, selectProject, retry: initialize, refreshTasks }), [state, selectWorkspace, selectProject, initialize, refreshTasks]);
  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}

export function useProduct() {
  const value = useContext(ProductContext);
  if (value === null) throw new Error("useProduct must be used within ProductProvider.");
  return value;
}

function chooseId<T extends { id: number }>(items: T[], preferredId: number | null): number | null {
  return items.some((item) => item.id === preferredId) ? preferredId : (items[0]?.id ?? null);
}

function userMap(users: User[]): Record<number, User> {
  return Object.fromEntries(users.map((user) => [user.id, user]));
}

function readStoredId(key: string): number | null {
  try {
    const value = window.localStorage.getItem(key);
    const id = value === null ? NaN : Number(value);
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch { return null; }
}

function persistId(key: string, id: number | null) {
  try {
    if (id === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, String(id));
  } catch { /* storage is optional */ }
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error("Could not load product data.");
}
