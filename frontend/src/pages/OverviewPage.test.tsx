import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { OverviewPage } from "./OverviewPage";

vi.mock("../app/ProductContext", () => ({ useProduct: vi.fn() }));
import { useProduct } from "../app/ProductContext";

describe("OverviewPage", () => {
  it("aggregates workspace metrics, groups, my tasks, and project progress", () => {
    vi.mocked(useProduct).mockReturnValue(state() as never);
    render(<MemoryRouter><OverviewPage /></MemoryRouter>);
    expect(screen.getByText("Projects").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Total tasks").nextSibling).toHaveTextContent("3");
    expect(screen.getByText("Completed").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Completion").nextSibling).toHaveTextContent("33%");
    expect(screen.getByText("Mine")).toBeInTheDocument();
    expect(screen.getAllByText("Alpha").at(-1)?.parentElement).toHaveTextContent("1/3");
    expect(screen.getByText("Beta").closest("button")).toHaveTextContent("No tasks yet");
  });

  it("shows empty workspace project and task states", () => {
    vi.mocked(useProduct).mockReturnValue({ ...state(), projects: [], workspaceTasks: {} } as never);
    render(<MemoryRouter><OverviewPage /></MemoryRouter>);
    expect(screen.getByText("No tasks are assigned to you in this workspace.")).toBeInTheDocument();
    expect(screen.getByText("No projects in this workspace.")).toBeInTheDocument();
  });
});

function state() {
  const tasks = [
    { id: 1, project_id: 1, title: "Mine", description: null, status: "TODO" as const, priority: "HIGH" as const, assignee_user_id: 7 },
    { id: 2, project_id: 1, title: "Done", description: null, status: "DONE" as const, priority: "LOW" as const, assignee_user_id: null },
    { id: 3, project_id: 1, title: "Moving", description: null, status: "IN_PROGRESS" as const, priority: "MEDIUM" as const, assignee_user_id: null },
  ];
  return { projects: [{ id: 1, workspace_id: 1, name: "Alpha", description: null }, { id: 2, workspace_id: 1, name: "Beta", description: null }], workspaceTasks: { 1: tasks, 2: [] }, currentUser: { id: 7, name: "User", email: "user@strata.local" }, selectedWorkspaceId: 1, status: "ready" as const, retry: vi.fn(), selectProject: vi.fn() };
}
