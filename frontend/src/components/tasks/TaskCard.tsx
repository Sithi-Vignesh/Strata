import type { Task, TaskStatus, User } from "../../types/product";
import { TASK_STATUSES } from "../../types/product";
import { PriorityBadge } from "./PriorityBadge";
import { DueDate } from "./DueDate";

export function TaskCard({ task, memberUsers, onStatusChange, statusPending, onOpen, onDragStart, onDragEnd }: { task: Task; memberUsers: Record<number, User>; onStatusChange?: (task: Task, status: TaskStatus) => void; statusPending?: boolean; onOpen?: (task: Task) => void; onDragStart?: (task: Task) => void; onDragEnd?: () => void }) {
  return (
    <article aria-busy={statusPending} className={`kanban-card ${statusPending ? "kanban-card-pending" : ""}`} draggable={Boolean(onDragStart) && !statusPending} onDragEnd={onDragEnd} onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", String(task.id)); onDragStart?.(task); }}>
      <span className="task-id-label">STR-{task.id}</span>
      {onOpen ? <button className="kanban-card-title" onClick={() => onOpen(task)} type="button">{task.title}</button> : <p className="kanban-card-title">{task.title}</p>}
      {task.description && <p className="kanban-card-description">{task.description}</p>}
      {task.due_date && <DueDate dueDate={task.due_date} status={task.status} />}
      <div className="kanban-card-meta">
        <PriorityBadge priority={task.priority} />
        <span className="truncate text-xs text-[var(--strata-subtle)]">{task.assignee_user_id === null ? "Unassigned" : (memberUsers[task.assignee_user_id]?.name ?? "Unknown member")}</span>
      </div>
      {onStatusChange && <label className="kanban-move"><span>Move to</span><select aria-label={`Move ${task.title} to status`} disabled={statusPending} onChange={(event) => onStatusChange(task, event.target.value as TaskStatus)} value={task.status}>{TASK_STATUSES.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></label>}
    </article>
  );
}
