import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/product";
import { StrataApiError } from "../api/strata";
import type { Task } from "../types/product";
import { TasksPage } from "../pages/TasksPage";
import { ProductProvider, useProduct } from "./ProductContext";

vi.mock("../api/product");
const user = { id: 1, name: "Owner", email: "owner@example.local" };
const taskA: Task = { id: 11, project_id: 10, title: "Task in A", description: null, status: "TODO", priority: "HIGH", assignee_user_id: null };
const taskB: Task = { ...taskA, id: 21, project_id: 20, title: "Task in B" };
let product: ReturnType<typeof useProduct>;
function Probe() { product = useProduct(); return <output>{product.status}:{product.selectedWorkspaceId}:{product.selectedProjectId}:{product.tasks.map(t => t.title).join(",")}</output>; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function mount(withTasks = false) { return render(<ProductProvider user={user}><Probe />{withTasks && <TasksPage />}</ProductProvider>); }
beforeEach(() => {
  vi.mocked(api.listUserWorkspaces).mockResolvedValue([{ id: 1, name: "A", kind: "COLLABORATIVE" }, { id: 2, name: "B", kind: "COLLABORATIVE" }]);
  vi.mocked(api.listWorkspaceProjects).mockImplementation(async id => [{ id: id * 10, workspace_id: id, name: id === 1 ? "Project A" : "Project B", description: null }]);
  vi.mocked(api.listWorkspaceMembers).mockImplementation(async id => [{ workspace_id: id, user_id: 1, role: "OWNER", name: user.name, email: user.email, account_state: "ACTIVE" }]);
  vi.mocked(api.listProjectTasks).mockImplementation(async id => [id === 10 ? taskA : taskB]);
  vi.mocked(api.listTaskNotes).mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.resetAllMocks(); window.localStorage.clear(); });

describe("adversarial product lifecycle", () => {
  it("does not apply an old mutation refresh to a newly selected workspace", async () => {
    mount(); await screen.findByText("ready:1:10:Task in A");
    // Mutation handlers retain this callback while their network request is pending.
    const oldRefresh = product.refreshTasks;
    act(() => product.selectWorkspace(2));
    await screen.findByText("ready:2:20:Task in B");
    await act(async () => oldRefresh());
    expect(product.selectedProjectId).toBe(20);
    expect(product.tasks).toEqual([taskB]);
    expect(Object.keys(product.workspaceTasks)).toEqual(["20"]);
  });

  it("ignores a task refresh response that arrives after a workspace switch", async () => {
    mount(); await screen.findByText("ready:1:10:Task in A");
    const pending = deferred<Task[]>();
    vi.mocked(api.listProjectTasks).mockReturnValueOnce(pending.promise);
    let refresh!: Promise<void>;
    act(() => { refresh = product.refreshTasks(); });
    act(() => product.selectWorkspace(2));
    await screen.findByText("ready:2:20:Task in B");
    await act(async () => { pending.resolve([{ ...taskA, title: "Late A" }]); await refresh; });
    expect(product.tasks).toEqual([taskB]);
  });

  it("keeps the newest workspace when an older workspace load finishes last", async () => {
    mount(); await screen.findByText("ready:1:10:Task in A");
    const pending = deferred<Awaited<ReturnType<typeof api.listWorkspaceProjects>>>();
    vi.mocked(api.listWorkspaceProjects).mockReturnValueOnce(pending.promise);
    act(() => product.selectWorkspace(2));
    act(() => product.selectWorkspace(1));
    await screen.findByText("ready:1:10:Task in A");
    await act(async () => pending.resolve([{ id: 20, workspace_id: 2, name: "Project B", description: null }]));
    expect(product.selectedWorkspaceId).toBe(1);
    expect(product.tasks).toEqual([taskA]);
  });

  it("clears revoked workspace data after an authorization failure", async () => {
    mount(); await screen.findByText("ready:1:10:Task in A");
    vi.mocked(api.listProjectTasks).mockRejectedValueOnce(new StrataApiError(403, "FORBIDDEN", "Membership removed"));
    await act(async () => { await expect(product.refreshTasks()).rejects.toMatchObject({ status: 403 }); });
    expect(product.status).toBe("error");
    expect(product.tasks).toEqual([]);
    expect(product.workspaceTasks).toEqual({});
    expect(product.projects).toEqual([]);
    expect(product.members).toEqual([]);
    expect(product.memberUsers).toEqual({});
  });

  it("closes a committed create form when only the follow-up refresh fails", async () => {
    mount(true); await screen.findByRole("button", { name: "New task" });
    vi.mocked(api.createTask).mockResolvedValue({ ...taskA, id: 12, title: "Created once" });
    vi.mocked(api.listProjectTasks).mockRejectedValueOnce(new Error("Refresh offline"));
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Created once" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));
    await screen.findByText("Task was created, but the latest task list could not be refreshed.");
    expect(screen.queryByRole("dialog", { name: "New task" })).not.toBeInTheDocument();
    expect(api.createTask).toHaveBeenCalledTimes(1);
  });

  it("refreshes an open task detail from the canonical task response", async () => {
    mount(true); await screen.findByRole("button", { name: "Task in A" });
    fireEvent.click(screen.getByRole("button", { name: "Task in A" }));
    await screen.findByText("No notes yet.");
    vi.mocked(api.listProjectTasks).mockResolvedValueOnce([{ ...taskA, title: "Renamed concurrently", status: "DONE" }]);
    await act(async () => product.refreshTasks());
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Renamed concurrently");
  });

  it("closes a task detail when refresh reveals that access was revoked", async () => {
    mount(true); await screen.findByRole("button", { name: "Task in A" });
    fireEvent.click(screen.getByRole("button", { name: "Task in A" }));
    await screen.findByText("No notes yet.");
    vi.mocked(api.listProjectTasks).mockRejectedValueOnce(new StrataApiError(403, "FORBIDDEN", "Membership removed"));
    await act(async () => { await product.refreshTasks().catch(() => undefined); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Task in A")).not.toBeInTheDocument();
  });

  it("falls back after deleting the selected project and workspace", async () => {
    mount(); await screen.findByText("ready:1:10:Task in A");
    vi.mocked(api.listWorkspaceProjects).mockResolvedValueOnce([]);
    await act(async () => product.refreshWorkspace());
    expect(product.selectedWorkspaceId).toBe(1);
    expect(product.selectedProjectId).toBeNull();
    expect(product.tasks).toEqual([]);
    vi.mocked(api.listUserWorkspaces).mockResolvedValueOnce([{ id: 2, name: "B", kind: "COLLABORATIVE" }]);
    await act(async () => product.refreshWorkspace());
    expect(product.selectedWorkspaceId).toBe(2);
    expect(product.selectedProjectId).toBe(20);
    expect(product.tasks).toEqual([taskB]);
  });
});
