import type { TaskPriority } from "../../types/product";
import { formatTaskPriority } from "./taskPresentation";

const styles: Record<TaskPriority, string> = {
  LOW: "priority-low",
  MEDIUM: "priority-medium",
  HIGH: "priority-high",
};

export function PriorityBadge({ priority }: { priority: TaskPriority }) {
  return <span className={`priority-badge ${styles[priority]}`}><i aria-hidden="true" />{formatTaskPriority(priority)}</span>;
}
