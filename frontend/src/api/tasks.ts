import { executeSqlProfile } from "./strata";
import type { QueryResponse, SqlRow } from "../types/api";
import { TASK_PRIORITIES, TASK_STATUSES, type Task, type TaskPriority, type TaskStatus, type TaskStatusSummary } from "../types/task";

const TASK_COLUMNS = ["id", "title", "status", "priority", "assignee", "project"] as const;
const SUMMARY_COLUMNS = ["status", "count_star"] as const;
const TASK_SELECT = "SELECT id, title, status, priority, assignee, project FROM tasks";

export async function getTaskStatusSummary(): Promise<TaskStatusSummary> {
  const result = await requireQuery("SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY status ASC");
  expectColumns(result, SUMMARY_COLUMNS);

  const summary = new Map<TaskStatus, number>();
  for (const row of result.rows) {
    const [status, count] = row;
    if (!isTaskStatus(status) || typeof count !== "number" || !Number.isFinite(count) || count < 0) {
      throw new Error("Strata returned an invalid task status summary.");
    }
    if (summary.has(status)) {
      throw new Error("Strata returned duplicate task status summary rows.");
    }
    summary.set(status, count);
  }

  if (summary.size !== TASK_STATUSES.length || TASK_STATUSES.some((status) => !summary.has(status))) {
    throw new Error("Strata returned an incomplete task status summary.");
  }

  return Object.fromEntries(TASK_STATUSES.map((status) => [status, summary.get(status)!])) as TaskStatusSummary;
}

export async function getTasks(): Promise<Task[]> {
  return mapTasks(await requireQuery(`${TASK_SELECT} ORDER BY id ASC LIMIT 40`));
}

export async function getBoardTasks(): Promise<Record<TaskStatus, Task[]>> {
  const taskGroups = await Promise.all(TASK_STATUSES.map(async (status) => {
    const tasks = mapTasks(await requireQuery(`${TASK_SELECT} WHERE status = '${status}' ORDER BY id ASC LIMIT 5`));
    if (tasks.some((task) => task.status !== status)) {
      throw new Error("Strata returned tasks for an unexpected board status.");
    }
    return [status, tasks] as const;
  }));

  return Object.fromEntries(taskGroups) as Record<TaskStatus, Task[]>;
}

async function requireQuery(sql: string): Promise<QueryResponse> {
  const response = await executeSqlProfile(sql);
  if (response.kind !== "query") {
    throw new Error("Strata returned a command response where task data was expected.");
  }
  return response;
}

function mapTasks(result: QueryResponse): Task[] {
  expectColumns(result, TASK_COLUMNS);
  return result.rows.map(mapTaskRow);
}

function expectColumns(result: QueryResponse, expected: readonly string[]) {
  const actual = result.columns.map((column) => column.name);
  if (actual.length !== expected.length || actual.some((name, index) => name !== expected[index])) {
    throw new Error(`Strata returned unexpected task data columns: ${actual.join(", ")}.`);
  }
}

function mapTaskRow(row: SqlRow): Task {
  const [id, title, status, priority, assignee, project] = row;
  if (typeof id !== "number" || !Number.isInteger(id) || typeof title !== "string" || !isTaskStatus(status) || !isTaskPriority(priority) || (assignee !== null && typeof assignee !== "string") || typeof project !== "string") {
    throw new Error("Strata returned an invalid task row.");
  }
  return { id, title, status, priority, assignee, project };
}

function isTaskStatus(value: unknown): value is TaskStatus {
  return typeof value === "string" && TASK_STATUSES.includes(value as TaskStatus);
}

function isTaskPriority(value: unknown): value is TaskPriority {
  return typeof value === "string" && TASK_PRIORITIES.includes(value as TaskPriority);
}
