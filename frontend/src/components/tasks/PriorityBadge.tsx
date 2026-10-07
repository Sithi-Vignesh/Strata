import type { TaskPriority } from "../../types/product";
import { formatTaskPriority } from "./taskPresentation";

const styles: Record<TaskPriority, string> = {
  LOW: "text-[var(--strata-muted)]",
  MEDIUM: "text-slate-700",
  HIGH: "text-amber-800",
};

export function PriorityBadge({ priority }: { priority: TaskPriority }) {
  return <span className={`text-xs font-semibold ${styles[priority]}`}>{formatTaskPriority(priority)}</span>;
}
