import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BoardPage } from "./BoardPage";

vi.mock("../app/ProductContext", () => ({ useProduct: vi.fn() }));
vi.mock("../api/product", () => ({ updateTask: vi.fn() }));
import { useProduct } from "../app/ProductContext";
import { updateTask } from "../api/product";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("BoardPage", () => {
  it("groups canonical product tasks into exactly three read-only columns", () => {
    vi.mocked(useProduct).mockReturnValue(contextValue() as never);
    render(<BoardPage />);
    expect(screen.getByRole("heading", { name: "To do" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "In progress" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Done" })).toBeInTheDocument();
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
  });

  it("patches only status and refreshes canonical tasks", async () => {
    const refreshTasks = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useProduct).mockReturnValue(contextValue({ refreshTasks }) as never);
    vi.mocked(updateTask).mockResolvedValue({ id: 1, project_id: 1, title: "Task", description: null, status: "DONE", priority: "HIGH", assignee_user_id: null });
    render(<BoardPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Move Task to status" }), { target: { value: "DONE" } });
    await waitFor(() => expect(updateTask).toHaveBeenCalledWith(1, { status: "DONE" }));
    expect(refreshTasks).toHaveBeenCalledTimes(1);
  });
});

function contextValue(overrides = {}) {
  return { tasks: [{ id: 1, project_id: 1, title: "Task", description: null, status: "IN_PROGRESS", priority: "HIGH", assignee_user_id: null }], memberUsers: {}, selectedProjectId: 1, status: "ready", retry: vi.fn(), refreshTasks: vi.fn(), ...overrides };
}
