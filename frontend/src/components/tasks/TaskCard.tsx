import type { Task } from "../../types/task";
import { PriorityBadge } from "./PriorityBadge";

export function TaskCard({ task }: { task: Task }) {
  return (
    <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-3">
      <p className="text-sm font-medium leading-5 text-[var(--strata-text)]">{task.title}</p>
      <div className="mt-3 flex items-center justify-between gap-3">
        <PriorityBadge priority={task.priority} />
        <span className="truncate text-xs text-[var(--strata-subtle)]">{task.assignee ?? "Unassigned"}</span>
      </div>
      <p className="mt-2 truncate text-xs text-[var(--strata-muted)]">{task.project}</p>
    </article>
  );
}
