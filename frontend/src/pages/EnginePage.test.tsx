import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { EnginePage } from "./EnginePage";

describe("EnginePage", () => {
  it("explains Strata's engine architecture and links to the SQL Console", () => {
    render(<MemoryRouter><EnginePage /></MemoryRouter>);

    expect(screen.getByRole("heading", { level: 1, name: "Strata Database Engine" })).toBeInTheDocument();
    expect(screen.getByText("A relational database engine built from scratch in Python.")).toBeInTheDocument();
    expect(screen.getByText("The application is the workload; the custom DBMS is the innovation.")).toBeInTheDocument();
    ["SQL Frontend", "Bind", "Plan", "Execute", "Persist"].forEach((stage) => {
      expect(screen.getByRole("heading", { level: 3, name: stage })).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Persistent B+ Tree indexing" })).toBeInTheDocument();
    expect(screen.getByText(/4 KiB pages, slotted-page heap records, buffer pooling/)).toBeInTheDocument();
    expect(screen.getByText(/open \/ next \/ close/)).toBeInTheDocument();
    expect(screen.getByText("Volcano-style iterator execution")).toBeInTheDocument();
    expect(screen.getByText(/GROUP BY plus two-table INNER JOIN through nested-loop execution/)).toBeInTheDocument();
    expect(screen.getByText(/Overview, Tasks, and Board use the product REST API/)).toBeInTheDocument();
    expect(screen.getByText(/SQL Console remains a separate DBthon demo surface/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open SQL Console" })).toHaveAttribute("href", "/sql");
  });
});
