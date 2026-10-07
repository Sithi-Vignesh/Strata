import type { TaskPriority, TaskStatus } from "../../types/product";

const statusLabels: Record<TaskStatus, string> = {
  TODO: "To do",
  IN_PROGRESS: "In progress",
  DONE: "Done",
};

const priorityLabels: Record<TaskPriority, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
};

export function formatTaskStatus(status: TaskStatus) {
  return statusLabels[status];
}

export function formatTaskPriority(priority: TaskPriority) {
  return priorityLabels[priority];
}

export function formatTaskId(id: number) {
  return `#${String(id).padStart(3, "0")}`;
}
