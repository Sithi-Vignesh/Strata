import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BoardPage } from "./BoardPage";

vi.mock("../app/ProductContext", () => ({ useProduct: vi.fn() }));
import { useProduct } from "../app/ProductContext";

describe("BoardPage", () => {
  it("groups canonical product tasks into exactly three read-only columns", () => {
    vi.mocked(useProduct).mockReturnValue({ tasks: [{ id: 1, project_id: 1, title: "Task", description: null, status: "IN_PROGRESS", priority: "HIGH", assignee_user_id: null }], memberUsers: {}, selectedProjectId: 1, status: "ready", retry: vi.fn() } as never);
    render(<BoardPage />);
    expect(screen.getByRole("heading", { name: "To do" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "In progress" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Done" })).toBeInTheDocument();
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
  });
});
