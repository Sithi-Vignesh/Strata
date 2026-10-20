import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../api/product";
import { useProduct } from "../app/ProductContext";
import { ProjectsPage } from "./ProjectsPage";
vi.mock("../api/product");
vi.mock("../app/ProductContext", () => ({ useProduct: vi.fn() }));
const refresh = vi.fn();
const project = { id: 9, workspace_id: 3, name: "Release", description: "Original", created_by_user_id: 1 };
const state = { projects: [] as typeof project[], workspaces: [{ id: 3, name: "Team", kind: "COLLABORATIVE" as const }], members: [{ workspace_id: 3, user_id: 1, name: "Owner", email: "owner@example.com", role: "OWNER" as const, account_state: "ACTIVE" }], currentUser: { id: 1, name: "Owner", email: "owner@example.com" }, selectedWorkspaceId: 3, selectedProjectId: null, memberUsers: {}, tasks: [], workspaceTasks: {}, status: "ready" as const, error: null, selectProject: vi.fn(), selectWorkspace: vi.fn(), refreshWorkspace: refresh, refreshTasks: vi.fn(), retry: vi.fn() };
beforeEach(() => { vi.mocked(useProduct).mockReturnValue(state); refresh.mockResolvedValue(undefined); });
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.restoreAllMocks(); });
function show() { return render(<MemoryRouter><ProjectsPage /></MemoryRouter>); }
it("creates the first project in an empty collaborative workspace and selects it", async () => {
  vi.mocked(api.createProject).mockResolvedValue(project); show();
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a project name.");
  expect(api.createProject).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Release" } });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledWith({ workspaceId: 3, projectId: 9 }));
  expect(api.createProject).toHaveBeenCalledWith(3, { name: "Release", description: null });
});
it("sends only edited project fields and shows dependency errors on delete", async () => {
  vi.mocked(useProduct).mockReturnValue({ ...state, projects: [project] });
  vi.mocked(api.updateProject).mockResolvedValue({ ...project, name: "Renamed" });
  vi.mocked(api.deleteProject).mockRejectedValue(new Error("Cannot delete a project that still has tasks."));
  vi.spyOn(window, "confirm").mockReturnValue(true); show();
  fireEvent.click(screen.getByRole("button", { name: "Edit project" }));
  fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Renamed" } });
  fireEvent.click(screen.getByRole("button", { name: "Save project" }));
  await waitFor(() => expect(api.updateProject).toHaveBeenCalledWith(9, { name: "Renamed" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Delete project" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("still has tasks");
});
it("renames and deletes a workspace and refreshes available selections", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true); show();
  fireEvent.change(screen.getByLabelText("Workspace name"), { target: { value: "Renamed team" } });
  fireEvent.click(screen.getByRole("button", { name: "Save workspace" }));
  await waitFor(() => expect(api.updateWorkspace).toHaveBeenCalledWith(3, "Renamed team"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Delete workspace" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Delete workspace" }));
  await waitFor(() => expect(api.deleteWorkspace).toHaveBeenCalledWith(3));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
});
it("limits workspace settings and creator deletion controls for members", () => {
  vi.mocked(useProduct).mockReturnValue({ ...state, projects: [project], currentUser: { id: 2, name: "Member", email: "member@example.com" } }); show();
  expect(screen.queryByRole("button", { name: "Delete workspace" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete project" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create project" })).toBeEnabled();
});

it("does not switch back to an old workspace when a pending create completes", async () => {
  let resolve!: (value: typeof project) => void;
  vi.mocked(api.createProject).mockReturnValue(new Promise((done) => { resolve = done; }));
  const view = show();
  fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Release" } });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));
  vi.mocked(useProduct).mockReturnValue({ ...state, selectedWorkspaceId: 4, workspaces: [{ id: 4, name: "Elsewhere", kind: "COLLABORATIVE" }] });
  view.rerender(<MemoryRouter><ProjectsPage /></MemoryRouter>);
  resolve(project);
  await waitFor(() => expect(screen.getByRole("button", { name: "Create project" })).toBeEnabled());
  expect(refresh).not.toHaveBeenCalled();
});
