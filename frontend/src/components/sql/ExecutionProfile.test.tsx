import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ExecutionProfile } from "./ExecutionProfile";

afterEach(cleanup);

describe("ExecutionProfile", () => {
  it("renders a truthful TableScan profile", () => {
    render(<ExecutionProfile profile={{ access_path: "TableScan", table: "tasks", index: null, condition: null, metrics: { tuples_examined: 1000 } }} />);
    expect(screen.getByRole("heading", { name: "Execution Profile" })).toBeInTheDocument();
    expect(screen.getAllByText("TableScan").length).toBeGreaterThan(0);
    expect(screen.getAllByText("tasks").length).toBeGreaterThan(0);
    expect(screen.getByText("Not used")).toBeInTheDocument();
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getByText("Tuples read from the table scan.")).toBeInTheDocument();
    expect(screen.queryByText(/B\+ Tree index/)).not.toBeInTheDocument();
  });

  it("renders IndexScan metadata, real metrics, and the B+ Tree flow", () => {
    render(<ExecutionProfile profile={{
      access_path: "IndexScan", table: "events", index: "events_kind_idx",
      condition: { column: "kind", operator: "=", literal: "O'Brien" },
      metrics: { tree_pages_visited: 3, leaf_entries_examined: 1201, rids_selected: 200, rows_fetched: 199 },
    }} />);
    expect(screen.getAllByText("IndexScan").length).toBeGreaterThan(0);
    expect(screen.getAllByText("events_kind_idx").length).toBeGreaterThan(0);
    expect(screen.getByText("kind = 'O''Brien'")).toBeInTheDocument();
    expect(screen.getByText("1,201")).toBeInTheDocument();
    expect(screen.getByText("Record identifiers selected")).toBeInTheDocument();
    expect(screen.getByText("B+ Tree pages visited for the index lookup.")).toBeInTheDocument();
    expect(screen.getByText((_content, node) => node?.textContent === "200 record identifiers selected")).toBeInTheDocument();
    expect(screen.getByText((_content, node) => node?.textContent === "199 rows fetched")).toBeInTheDocument();
    expect(screen.getByText(/eligible comparison on the indexed/)).toHaveTextContent("events_kind_idx");
    expect(screen.getByText(/eligible comparison on the indexed/)).toHaveTextContent("kind");
  });

  it("formats numeric and boolean conditions", () => {
    const { rerender } = render(<ExecutionProfile profile={{ access_path: "IndexScan", table: "metrics", index: "metrics_score_idx", condition: { column: "score", operator: ">=", literal: 12.5 }, metrics: { tree_pages_visited: 1, leaf_entries_examined: 1, rids_selected: 1, rows_fetched: 1 } }} />);
    expect(screen.getByText("score >= 12.5")).toBeInTheDocument();
    rerender(<ExecutionProfile profile={{ access_path: "IndexScan", table: "flags", index: "flags_active_idx", condition: { column: "active", operator: "=", literal: true }, metrics: { tree_pages_visited: 1, leaf_entries_examined: 1, rids_selected: 1, rows_fetched: 1 } }} />);
    expect(screen.getByText("active = TRUE")).toBeInTheDocument();
  });

  it("uses singular B+ Tree flow labels for one selected record and fetched row", () => {
    render(<ExecutionProfile profile={{ access_path: "IndexScan", table: "single", index: "single_id_idx", condition: { column: "id", operator: "=", literal: 1 }, metrics: { tree_pages_visited: 1, leaf_entries_examined: 1, rids_selected: 1, rows_fetched: 1 } }} />);
    expect(screen.getByText((_content, node) => node?.textContent === "1 record identifier selected")).toBeInTheDocument();
    expect(screen.getByText((_content, node) => node?.textContent === "1 row fetched")).toBeInTheDocument();
  });

  it("treats a null query profile as normally unavailable", () => {
    render(<ExecutionProfile profile={null} />);
    expect(screen.getByText("Unavailable for this query shape.")).toBeInTheDocument();
  });
});
