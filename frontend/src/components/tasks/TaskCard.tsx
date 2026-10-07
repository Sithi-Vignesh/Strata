import type { Task, User } from "../../types/product";
import { PriorityBadge } from "./PriorityBadge";

export function TaskCard({ task, memberUsers }: { task: Task; memberUsers: Record<number, User> }) {
  return (
    <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-3">
      <p className="text-sm font-medium leading-5 text-[var(--strata-text)]">{task.title}</p>
      <div className="mt-3 flex items-center justify-between gap-3">
        <PriorityBadge priority={task.priority} />
        <span className="truncate text-xs text-[var(--strata-subtle)]">{task.assignee_user_id === null ? "Unassigned" : (memberUsers[task.assignee_user_id]?.name ?? "Unknown member")}</span>
      </div>
      {task.description && <p className="mt-2 line-clamp-2 text-xs text-[var(--strata-muted)]">{task.description}</p>}
    </article>
  );
}
