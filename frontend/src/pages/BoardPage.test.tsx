import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getBoardTasks } from "../api/tasks";
import { BoardPage } from "./BoardPage";

vi.mock("../api/tasks", () => ({ getBoardTasks: vi.fn() }));

const boardMock = vi.mocked(getBoardTasks);

afterEach(() => {
  vi.resetAllMocks();
});

describe("BoardPage", () => {
  it("shows loading before board requests resolve", () => {
    boardMock.mockReturnValue(new Promise(() => undefined));

    render(<BoardPage />);

    expect(screen.getByText("Loading board…")).toBeInTheDocument();
  });

  it("renders the five workflow columns and real task cards", async () => {
    boardMock.mockResolvedValue({
      TODO: [{ id: 1, title: "Implement storage task 001", status: "TODO", priority: "LOW", assignee: null, project: "Strata Engine" }],
      IN_PROGRESS: [], REVIEW: [], BLOCKED: [], DONE: [],
    });

    render(<BoardPage />);

    expect(await screen.findByRole("heading", { name: "To do" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "In progress" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Blocked" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Done" })).toBeInTheDocument();
    expect(screen.getByText("Implement storage task 001")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
  });

  it("shows a truthful error state", async () => {
    boardMock.mockRejectedValue(new Error("backend unavailable"));

    render(<BoardPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load workspace data");
  });
});
