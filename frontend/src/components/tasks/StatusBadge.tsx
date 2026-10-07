import type { TaskStatus } from "../../types/product";
import { formatTaskStatus } from "./taskPresentation";

const styles: Record<TaskStatus, string> = {
  TODO: "border-slate-200 bg-slate-100 text-slate-700",
  IN_PROGRESS: "border-indigo-200 bg-indigo-50 text-indigo-800",
  DONE: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${styles[status]}`}>{formatTaskStatus(status)}</span>;
}
