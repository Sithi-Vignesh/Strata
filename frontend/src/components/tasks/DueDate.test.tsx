import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DueDate, dueState, formatDateOnly } from "./DueDate";

afterEach(cleanup);

describe("due-date presentation", () => {
  it("classifies overdue, today, soon, and future calendar dates", () => {
    expect(dueState("2026-10-18", "2026-10-19")).toBe("overdue");
    expect(dueState("2026-10-19", "2026-10-19")).toBe("today");
    expect(dueState("2026-10-26", "2026-10-19")).toBe("soon");
    expect(dueState("2026-10-27", "2026-10-19")).toBe("future");
  });

  it("formats the supplied date components without a local-timezone shift", () => {
    const formatted = formatDateOnly("2026-01-01");
    expect(formatted).toMatch(/2026/);
    expect(formatted).toMatch(/1/);
    render(<DueDate dueDate="2000-01-01" status="TODO" />);
    expect(screen.getByText(/Overdue:/)).toBeInTheDocument();
  });

  it("supports null dates and does not mark completed tasks overdue", () => {
    const { rerender } = render(<DueDate dueDate={null} status="TODO" />);
    expect(screen.getByText("No due date")).toBeInTheDocument();
    rerender(<DueDate dueDate="2000-01-01" status="DONE" />);
    expect(screen.queryByText(/Overdue/)).not.toBeInTheDocument();
  });
});
