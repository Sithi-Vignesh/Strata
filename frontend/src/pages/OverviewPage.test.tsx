import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getTaskStatusSummary } from "../api/tasks";
import { OverviewPage } from "./OverviewPage";

vi.mock("../api/tasks", () => ({ getTaskStatusSummary: vi.fn() }));

const summaryMock = vi.mocked(getTaskStatusSummary);

afterEach(() => {
  vi.resetAllMocks();
});

describe("OverviewPage", () => {
  it("shows loading before the real summary resolves", () => {
    summaryMock.mockReturnValue(new Promise(() => undefined));

    render(<OverviewPage />);

    expect(screen.getByText("Loading workspace summary…")).toBeInTheDocument();
  });

  it("renders database-derived summary values", async () => {
    summaryMock.mockResolvedValue({ TODO: 200, IN_PROGRESS: 200, REVIEW: 200, BLOCKED: 200, DONE: 200 });

    render(<OverviewPage />);

    expect(await screen.findByText("1000")).toBeInTheDocument();
    expect(screen.getAllByText("200")).toHaveLength(8);
    expect(screen.getByRole("heading", { name: "Work by status" })).toBeInTheDocument();
  });

  it("shows a truthful error state", async () => {
    summaryMock.mockRejectedValue(new Error("backend unavailable"));

    render(<OverviewPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load workspace data");
  });
});
