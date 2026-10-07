import type { Task, TaskStatus, User } from "../../types/product";
import { TASK_STATUSES } from "../../types/product";
import { PriorityBadge } from "./PriorityBadge";

export function TaskCard({ task, memberUsers, onStatusChange, statusPending, onOpen }: { task: Task; memberUsers: Record<number, User>; onStatusChange?: (task: Task, status: TaskStatus) => void; statusPending?: boolean; onOpen?: (task: Task) => void }) {
  return (
    <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] p-3">
      {onOpen ? <button className="text-left text-sm font-medium leading-5 text-[var(--strata-text)] hover:underline" onClick={() => onOpen(task)} type="button">{task.title}</button> : <p className="text-sm font-medium leading-5 text-[var(--strata-text)]">{task.title}</p>}
      <div className="mt-3 flex items-center justify-between gap-3">
        <PriorityBadge priority={task.priority} />
        <span className="truncate text-xs text-[var(--strata-subtle)]">{task.assignee_user_id === null ? "Unassigned" : (memberUsers[task.assignee_user_id]?.name ?? "Unknown member")}</span>
      </div>
      {task.description && <p className="mt-2 line-clamp-2 text-xs text-[var(--strata-muted)]">{task.description}</p>}
      {onStatusChange && <label className="mt-3 block text-xs font-semibold text-[var(--strata-muted)]">Move to<select aria-label={`Move ${task.title} to status`} className="ml-2 rounded border border-[var(--strata-border)] bg-white px-1 py-0.5 text-xs" disabled={statusPending} onChange={(event) => onStatusChange(task, event.target.value as TaskStatus)} value={task.status}>{TASK_STATUSES.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></label>}
    </article>
  );
}
