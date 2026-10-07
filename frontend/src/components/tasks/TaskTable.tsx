import type { Task, User } from "../../types/product";
import { PriorityBadge } from "./PriorityBadge";
import { StatusBadge } from "./StatusBadge";
import { formatTaskId } from "./taskPresentation";

export function TaskTable({ tasks, memberUsers, onEdit, onDelete }: { tasks: Task[]; memberUsers: Record<number, User>; onEdit: (task: Task) => void; onDelete: (task: Task) => void }) {
  return (
    <div className="mt-6 overflow-x-auto rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)]">
      <table className="min-w-[48rem] w-full border-collapse text-left text-sm">
        <thead className="border-b border-[var(--strata-border)] bg-slate-50 text-xs uppercase tracking-[0.08em] text-[var(--strata-subtle)]">
          <tr>
            <th className="px-4 py-3 font-semibold" scope="col">ID</th>
            <th className="min-w-80 px-4 py-3 font-semibold" scope="col">Task</th>
            <th className="px-4 py-3 font-semibold" scope="col">Status</th>
            <th className="px-4 py-3 font-semibold" scope="col">Priority</th>
            <th className="px-4 py-3 font-semibold" scope="col">Assignee</th>
            <th className="px-4 py-3 font-semibold" scope="col">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--strata-border)]">
          {tasks.map((task) => (
            <tr className="bg-[var(--strata-surface)]" key={task.id}>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-[var(--strata-subtle)]">{formatTaskId(task.id)}</td>
              <td className="px-4 py-3 font-medium text-[var(--strata-text)]">{task.title}</td>
              <td className="whitespace-nowrap px-4 py-3"><StatusBadge status={task.status} /></td>
              <td className="whitespace-nowrap px-4 py-3"><PriorityBadge priority={task.priority} /></td>
              <td className="whitespace-nowrap px-4 py-3 text-[var(--strata-muted)]">{task.assignee_user_id === null ? "Unassigned" : (memberUsers[task.assignee_user_id]?.name ?? "Unknown member")}</td>
              <td className="whitespace-nowrap px-4 py-3"><button className="font-semibold text-[var(--strata-accent)]" onClick={() => onEdit(task)} type="button">Edit</button><button className="ml-3 font-semibold text-rose-700" onClick={() => onDelete(task)} type="button">Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
