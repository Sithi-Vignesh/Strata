import type { TaskStatus } from "../../types/product";
import { formatTaskStatus } from "./taskPresentation";

const styles: Record<TaskStatus, string> = {
  TODO: "status-todo",
  IN_PROGRESS: "status-progress",
  DONE: "status-done",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`status-badge ${styles[status]}`}><i aria-hidden="true" />{formatTaskStatus(status)}</span>;
}
