import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getTasks } from "../api/tasks";
import { TasksPage } from "./TasksPage";

vi.mock("../api/tasks", () => ({ getTasks: vi.fn() }));

const tasksMock = vi.mocked(getTasks);

afterEach(() => {
  vi.resetAllMocks();
});

describe("TasksPage", () => {
  it("shows loading before rows resolve", () => {
    tasksMock.mockReturnValue(new Promise(() => undefined));

    render(<TasksPage />);

    expect(screen.getByText("Loading tasks…")).toBeInTheDocument();
  });

  it("renders formatted real task attributes", async () => {
    tasksMock.mockResolvedValue([{ id: 1, title: "Implement storage task 001", status: "IN_PROGRESS", priority: "HIGH", assignee: null, project: "Strata Engine" }]);

    render(<TasksPage />);

    expect(await screen.findByText("#001")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
  });

  it("shows a truthful error state", async () => {
    tasksMock.mockRejectedValue(new Error("backend unavailable"));

    render(<TasksPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load workspace data");
  });
});
