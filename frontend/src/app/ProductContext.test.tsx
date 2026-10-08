import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as productApi from "../api/product";
import { ProductProvider, useProduct } from "./ProductContext";

vi.mock("../api/product");

afterEach(() => { vi.resetAllMocks(); window.localStorage.clear(); });

describe("ProductContext", () => {
  it("initializes the authenticated user, first workspace/project, members, and canonical tasks", async () => {
    vi.mocked(productApi.getUser).mockResolvedValue({ id: 1, name: "Sithi", email: "sithi@strata.local" });
    vi.mocked(productApi.listUserWorkspaces).mockResolvedValue([{ id: 2, name: "Team" }]);
    vi.mocked(productApi.listWorkspaceProjects).mockResolvedValue([{ id: 3, workspace_id: 2, name: "Strata", description: null }]);
    vi.mocked(productApi.listWorkspaceMembers).mockResolvedValue([{ workspace_id: 2, user_id: 1, role: "OWNER" }]);
    vi.mocked(productApi.listProjectTasks).mockResolvedValue([{ id: 4, project_id: 3, title: "Read path", description: null, status: "TODO", priority: "HIGH", assignee_user_id: 1 }]);
    render(<ProductProvider user={{ id: 7, name: "Sithi", email: "sithi@strata.local" }}><Probe /></ProductProvider>);
    await waitFor(() => expect(screen.getByText("ready:2:3:1:Sithi")).toBeInTheDocument());
    expect(productApi.listUserWorkspaces).toHaveBeenCalledWith(7);
    expect(productApi.listProjectTasks).toHaveBeenCalledWith(3);
    expect(window.localStorage.getItem("strata.user.7.selectedWorkspaceId")).toBe("2");
    expect(window.localStorage.getItem("strata.user.7.selectedProjectId")).toBe("3");
  });

  it("falls back from invalid persisted selections", async () => {
    window.localStorage.setItem("strata.user.7.selectedWorkspaceId", "99");
    window.localStorage.setItem("strata.user.7.selectedProjectId", "88");
    vi.mocked(productApi.getUser).mockResolvedValue({ id: 1, name: "Sithi", email: "sithi@strata.local" });
    vi.mocked(productApi.listUserWorkspaces).mockResolvedValue([{ id: 2, name: "Team" }]);
    vi.mocked(productApi.listWorkspaceProjects).mockResolvedValue([]);
    vi.mocked(productApi.listWorkspaceMembers).mockResolvedValue([]);
    render(<ProductProvider user={{ id: 7, name: "Sithi", email: "sithi@strata.local" }}><Probe /></ProductProvider>);
    await waitFor(() => expect(screen.getByText("ready:2:none:0:none")).toBeInTheDocument());
    expect(window.localStorage.getItem("strata.user.7.selectedWorkspaceId")).toBe("2");
    expect(window.localStorage.getItem("strata.user.7.selectedProjectId")).toBeNull();
  });
});

function Probe() {
  const { status, selectedWorkspaceId, selectedProjectId, tasks, memberUsers } = useProduct();
  return <p>{`${status}:${selectedWorkspaceId ?? "none"}:${selectedProjectId ?? "none"}:${tasks.length}:${memberUsers[1]?.name ?? "none"}`}</p>;
}
