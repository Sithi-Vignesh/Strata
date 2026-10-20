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

  it("moves a dragged task only when dropped in a different status column", async () => {
    vi.mocked(useProduct).mockReturnValue(contextValue() as never);
    vi.mocked(updateTask).mockResolvedValue({ ...contextValue().tasks[0], status: "DONE" } as never);
    render(<BoardPage />);
    const card = screen.getByText("Task").closest("article") as HTMLElement;
    const done = screen.getByRole("heading", { name: "Done" }).closest("section") as HTMLElement;
    fireEvent.dragStart(card, { dataTransfer: { effectAllowed: "none", setData: vi.fn() } });
    fireEvent.dragOver(done, { dataTransfer: { dropEffect: "none" } });
    fireEvent.drop(done);
    await waitFor(() => expect(updateTask).toHaveBeenCalledWith(1, { status: "DONE" }));
  });

  it("keeps canonical state and reports a failed movement", async () => {
    vi.mocked(useProduct).mockReturnValue(contextValue() as never);
    vi.mocked(updateTask).mockRejectedValue(new Error("Status update failed"));
    render(<BoardPage />);
    fireEvent.change(screen.getByRole("combobox", { name: "Move Task to status" }), { target: { value: "DONE" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Status update failed");
    expect(screen.getByRole("combobox", { name: "Move Task to status" })).toHaveValue("IN_PROGRESS");
  });
});

function contextValue(overrides = {}) {
  return { tasks: [{ id: 1, project_id: 1, title: "Task", description: null, status: "IN_PROGRESS", priority: "HIGH", assignee_user_id: null }], memberUsers: {}, selectedProjectId: 1, status: "ready", retry: vi.fn(), refreshTasks: vi.fn(), ...overrides };
}
