import { afterEach, describe, expect, it, vi } from "vitest";
import { executeSqlProfile } from "./strata";
import { getTaskStatusSummary, getTasks } from "./tasks";
import type { QueryResponse, SqlRow } from "../types/api";

vi.mock("./strata", () => ({ executeSqlProfile: vi.fn() }));

const executeSqlProfileMock = vi.mocked(executeSqlProfile);

afterEach(() => {
  vi.resetAllMocks();
});

describe("task product-data client", () => {
  it("maps a valid task query and preserves a null assignee", async () => {
    executeSqlProfileMock.mockResolvedValue(taskQuery([[1, "Implement storage task 001", "TODO", "LOW", null, "Strata Engine"]]));

    await expect(getTasks()).resolves.toEqual([{
      id: 1,
      title: "Implement storage task 001",
      status: "TODO",
      priority: "LOW",
      assignee: null,
      project: "Strata Engine",
    }]);
    expect(executeSqlProfileMock).toHaveBeenCalledWith("SELECT id, title, status, priority, assignee, project FROM tasks ORDER BY id ASC LIMIT 40");
  });

  it("rejects a command response where task data is required", async () => {
    executeSqlProfileMock.mockResolvedValue({ kind: "command", affected_rows: 1, profile: null });

    await expect(getTasks()).rejects.toThrow("command response");
  });

  it("rejects unexpected task columns", async () => {
    executeSqlProfileMock.mockResolvedValue({ ...taskQuery([]), columns: [{ name: "title", type: "VARCHAR", nullable: false }] });

    await expect(getTasks()).rejects.toThrow("unexpected task data columns");
  });

  it("rejects malformed task fields", async () => {
    executeSqlProfileMock.mockResolvedValue(taskQuery([[1, "Task", "NOT_A_STATUS", "LOW", "Avery", "Website"]]));

    await expect(getTasks()).rejects.toThrow("invalid task row");
  });

  it("maps grouped task status counts", async () => {
    executeSqlProfileMock.mockResolvedValue({
      kind: "query",
      columns: [
        { name: "status", type: "VARCHAR", nullable: false },
        { name: "count_star", type: "BIGINT", nullable: false },
      ],
      rows: [["BLOCKED", 2], ["DONE", 4], ["IN_PROGRESS", 3], ["REVIEW", 1], ["TODO", 5]],
      row_count: 5,
      profile: null,
    });

    await expect(getTaskStatusSummary()).resolves.toEqual({ TODO: 5, IN_PROGRESS: 3, REVIEW: 1, BLOCKED: 2, DONE: 4 });
  });

  it("rejects incomplete grouped task status counts", async () => {
    executeSqlProfileMock.mockResolvedValue({
      kind: "query",
      columns: [
        { name: "status", type: "VARCHAR", nullable: false },
        { name: "count_star", type: "BIGINT", nullable: false },
      ],
      rows: [["TODO", 5]],
      row_count: 1,
      profile: null,
    });

    await expect(getTaskStatusSummary()).rejects.toThrow("incomplete task status summary");
  });
});

function taskQuery(rows: SqlRow[]): QueryResponse {
  return {
    kind: "query",
    columns: [
      { name: "id", type: "INTEGER", nullable: false },
      { name: "title", type: "VARCHAR", nullable: false },
      { name: "status", type: "VARCHAR", nullable: false },
      { name: "priority", type: "VARCHAR", nullable: false },
      { name: "assignee", type: "VARCHAR", nullable: true },
      { name: "project", type: "VARCHAR", nullable: false },
    ],
    rows,
    row_count: rows.length,
    profile: null,
  };
}
