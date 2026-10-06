import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { executeSqlProfile, StrataApiError } from "../api/strata";
import { SqlConsolePage } from "./SqlConsolePage";

vi.mock("../api/strata", () => ({ executeSqlProfile: vi.fn(), StrataApiError: class StrataApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
  }
} }));

const executeMock = vi.mocked(executeSqlProfile);
const tableScanSql = "SELECT id, title, status, priority\nFROM tasks\nWHERE priority = 'URGENT';";
const indexScanSql = "SELECT id, title, status, priority\nFROM tasks\nWHERE status = 'BLOCKED';";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("SqlConsolePage", () => {
  it("populates the Table Scan SQL by default and presets replace without executing", () => {
    render(<SqlConsolePage />);
    const editor = screen.getByLabelText("SQL statement");
    expect(editor).toHaveValue(tableScanSql);

    fireEvent.click(screen.getByRole("button", { name: "Index scan demo" }));
    expect(editor).toHaveValue(indexScanSql);
    fireEvent.click(screen.getByRole("button", { name: "Table scan demo" }));
    expect(editor).toHaveValue(tableScanSql);
    expect(executeMock).not.toHaveBeenCalled();
  });

  it("submits trimmed SQL and renders dynamic generic query values", async () => {
    executeMock.mockResolvedValueOnce({
      kind: "query",
      columns: [
        { name: "label", type: "VARCHAR", nullable: false },
        { name: "enabled", type: "BOOLEAN", nullable: false },
        { name: "optional", type: "VARCHAR", nullable: true },
      ],
      rows: [["Arbitrary value", true, null]],
      row_count: 1,
      profile: null,
    });
    render(<SqlConsolePage />);
    fireEvent.change(screen.getByLabelText("SQL statement"), { target: { value: "  SELECT label FROM items  " } });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    await waitFor(() => expect(executeMock).toHaveBeenCalledWith("SELECT label FROM items"));
    expect(await screen.findByRole("heading", { name: "Query results" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /label/i })).toBeInTheDocument();
    expect(screen.getByText("Arbitrary value")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
    expect(screen.getByText("NULL")).toBeInTheDocument();
    expect(screen.getByText("1 row returned")).toBeInTheDocument();
  });

  it("treats zero rows as a successful result", async () => {
    executeMock.mockResolvedValueOnce({ kind: "query", columns: [{ name: "id", type: "INTEGER", nullable: false }], rows: [], row_count: 0, profile: null });
    render(<SqlConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByText("0 rows returned")).toBeInTheDocument();
    expect(screen.getByText("This query returned no rows.")).toBeInTheDocument();
  });

  it("renders command outcomes with affected-row grammar", async () => {
    executeMock.mockResolvedValueOnce({ kind: "command", affected_rows: 1, profile: null });
    render(<SqlConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByText("Command completed")).toBeInTheDocument();
    expect(screen.getByText("1 row affected.")).toBeInTheDocument();
  });

  it("renders backend SQL errors without exposing a traceback", async () => {
    executeMock.mockRejectedValueOnce(new StrataApiError(400, "SQL_ERROR", "Expected FROM at position 7."));
    render(<SqlConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("SQL error");
    expect(alert).toHaveTextContent("Expected FROM at position 7.");
    expect(alert).toHaveTextContent("SQL_ERROR");
  });

  it("renders backend-unavailable guidance for network failures", async () => {
    executeMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<SqlConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the Strata backend. Check that it is running.");
  });

  it("does not submit blank SQL", () => {
    render(<SqlConsolePage />);
    fireEvent.change(screen.getByLabelText("SQL statement"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(executeMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a SQL statement before running it.");
  });

  it("disables execution controls and prevents duplicate runs while pending", async () => {
    let resolveExecution: (value: { kind: "command"; affected_rows: number; profile: null }) => void;
    executeMock.mockReturnValueOnce(new Promise((resolve) => { resolveExecution = resolve; }));
    render(<SqlConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Table scan demo" })).toBeDisabled();
    expect(executeMock).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByLabelText("SQL statement"), { key: "Enter", ctrlKey: true });
    expect(executeMock).toHaveBeenCalledTimes(1);
    resolveExecution!({ kind: "command", affected_rows: 0, profile: null });
    expect(await screen.findByText("0 rows affected.")).toBeInTheDocument();
  });

  it.each([
    ["Ctrl+Enter", { key: "Enter", ctrlKey: true }],
    ["Meta+Enter", { key: "Enter", metaKey: true }],
  ])("runs through %s but not plain Enter", async (_name, event) => {
    executeMock.mockResolvedValue({ kind: "command", affected_rows: 0, profile: null });
    render(<SqlConsolePage />);
    const editor = screen.getByLabelText("SQL statement");
    fireEvent.keyDown(editor, event);
    await waitFor(() => expect(executeMock).toHaveBeenCalledTimes(1));
    fireEvent.keyDown(editor, { key: "Enter" });
    expect(executeMock).toHaveBeenCalledTimes(1);
  });

  it("keeps a previous result during a later run and after its failure", async () => {
    executeMock.mockResolvedValueOnce({ kind: "command", affected_rows: 2, profile: null });
    render(<SqlConsolePage />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByText("2 rows affected.")).toBeInTheDocument();

    let rejectExecution: (reason: unknown) => void;
    executeMock.mockReturnValueOnce(new Promise((_, reject) => { rejectExecution = reject; }));
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(screen.getByText("2 rows affected.")).toBeInTheDocument();
    rejectExecution!(new TypeError("Failed to fetch"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
    expect(screen.getByText("2 rows affected.")).toBeInTheDocument();
  });

  it("retries the current editor SQL", async () => {
    executeMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    executeMock.mockResolvedValueOnce({ kind: "command", affected_rows: 0, profile: null });
    render(<SqlConsolePage />);
    fireEvent.change(screen.getByLabelText("SQL statement"), { target: { value: "SELECT 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    await screen.findByRole("alert");
    fireEvent.change(screen.getByLabelText("SQL statement"), { target: { value: "SELECT 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(executeMock).toHaveBeenLastCalledWith("SELECT 2"));
  });
});
