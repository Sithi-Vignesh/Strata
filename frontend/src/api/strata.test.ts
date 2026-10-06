import { afterEach, describe, expect, it, vi } from "vitest";
import { executeSqlProfile, getHealth, StrataApiError } from "./strata";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Strata API client", () => {
  it("returns the health response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      status: "ok",
      service: "strata_backend",
      engine: { name: "StrataEngine", status: "open", initialized: true },
    })));

    await expect(getHealth()).resolves.toMatchObject({ engine: { status: "open" } });
  });

  it("returns and narrows a query response with an index profile", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      kind: "query",
      columns: [{ name: "id", type: "INTEGER", nullable: false }],
      rows: [[4]],
      row_count: 1,
      profile: {
        access_path: "IndexScan",
        table: "tasks",
        index: "tasks_status_idx",
        condition: { column: "status", operator: "=", literal: "BLOCKED" },
        metrics: { tree_pages_visited: 2, leaf_entries_examined: 200, rids_selected: 200, rows_fetched: 200 },
      },
    })));

    const response = await executeSqlProfile("SELECT id FROM tasks WHERE status = 'BLOCKED'");
    expect(response.kind).toBe("query");
    if (response.kind === "query") {
      expect(response.profile?.access_path).toBe("IndexScan");
    }
  });

  it("returns a command response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      kind: "command", affected_rows: 1, profile: null,
    })));

    const response = await executeSqlProfile("INSERT INTO tasks VALUES (1001, 'Demo', 'TODO', 'LOW', NULL, 'Website')");
    expect(response).toMatchObject({ kind: "command", affected_rows: 1, profile: null });
  });

  it("preserves backend SQL errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: "SQL_ERROR", message: "Invalid SQL" },
    }, 400)));

    await expect(executeSqlProfile("SELECT FROM tasks")).rejects.toMatchObject({
      status: 400,
      code: "SQL_ERROR",
      message: "Invalid SQL",
    } satisfies Partial<StrataApiError>);
  });

  it("safely handles non-standard error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("gateway failure", { status: 502 })));

    await expect(getHealth()).rejects.toMatchObject({
      status: 502,
      code: "HTTP_502",
      message: "Request failed with status 502.",
    } satisfies Partial<StrataApiError>);
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
