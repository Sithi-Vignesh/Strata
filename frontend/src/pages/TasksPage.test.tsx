import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TasksPage } from "./TasksPage";

vi.mock("../app/ProductContext", () => ({ useProduct: vi.fn() }));
import { useProduct } from "../app/ProductContext";

describe("TasksPage", () => {
  it("renders resolved member names and clean unassigned tasks", () => {
    vi.mocked(useProduct).mockReturnValue({ tasks: [
      { id: 1, project_id: 1, title: "Assigned", description: null, status: "TODO", priority: "HIGH", assignee_user_id: 1 },
      { id: 2, project_id: 1, title: "Unassigned", description: null, status: "DONE", priority: "LOW", assignee_user_id: null },
    ], memberUsers: { 1: { id: 1, name: "Sithi", email: "sithi@strata.local" } }, selectedWorkspaceId: 1, selectedProjectId: 1, status: "ready", retry: vi.fn() } as never);
    render(<TasksPage />);
    expect(screen.getByText("Sithi")).toBeInTheDocument();
    expect(screen.getAllByText("Unassigned")).toHaveLength(2);
    expect(screen.getByText("To do")).toBeInTheDocument();
    expect(screen.queryByText("Urgent")).not.toBeInTheDocument();
  });
});
