import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MyTasksPage } from "./MyTasksPage";

vi.mock("../app/ProductContext", () => ({ useProduct: () => ({ refreshWorkspace: vi.fn().mockResolvedValue(undefined), selectedWorkspaceId: 2, workspaces: [{ id: 2, name: "Team B", kind: "COLLABORATIVE" }] }) }));
vi.mock("../api/product", () => ({ listMyTasks: vi.fn() }));
import { listMyTasks } from "../api/product";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const item = { id: 4, project_id: 3, workspace_id: 2, workspace_name: "Team B", project_name: "Launch", title: "Cross workspace task", description: null, status: "TODO" as const, priority: "HIGH" as const, assignee_user_id: 1, due_date: "2026-12-01" };

describe("MyTasksPage", () => {
  it("renders workspace-scoped results and sends backend filters and pagination", async () => {
    vi.mocked(listMyTasks).mockResolvedValue({ items: [item], total: 25, limit: 20, offset: 0 });
    render(<MemoryRouter><MyTasksPage /></MemoryRouter>);
    expect(await screen.findByText("Cross workspace task")).toBeInTheDocument();
    expect(screen.getByText("Team B / Launch")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "TODO" } });
    await waitFor(() => expect(listMyTasks).toHaveBeenLastCalledWith(expect.objectContaining({ workspace_id: 2, status: "TODO", sort: "updated_desc" })));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(listMyTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 })));
  });

  it("clears stale data when access is revoked", async () => {
    vi.mocked(listMyTasks).mockRejectedValue(new Error("Workspace access was revoked."));
    render(<MemoryRouter><MyTasksPage /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Workspace access was revoked.");
    expect(screen.queryByText("Cross workspace task")).not.toBeInTheDocument();
  });
});
