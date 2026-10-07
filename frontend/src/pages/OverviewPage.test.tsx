import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OverviewPage } from "./OverviewPage";

vi.mock("../app/ProductContext", () => ({ useProduct: vi.fn() }));
import { useProduct } from "../app/ProductContext";

describe("OverviewPage", () => {
  it("derives three product status metrics from canonical tasks", () => {
    vi.mocked(useProduct).mockReturnValue(productState([{ id: 1, status: "TODO" }, { id: 2, status: "DONE" }]) as never);
    render(<OverviewPage />);
    expect(screen.getByText("Total tasks").nextSibling).toHaveTextContent("2");
    expect(screen.getAllByText("To do")[0]?.nextSibling).toHaveTextContent("1");
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
  });
});

function productState(tasks: Array<{ id: number; status: "TODO" | "DONE" }>) {
  return { tasks: tasks.map((task) => ({ ...task, project_id: 1, title: "Task", description: null, priority: "HIGH" as const, assignee_user_id: null })), selectedWorkspaceId: 1, selectedProjectId: 1, status: "ready" as const, retry: vi.fn() };
}
