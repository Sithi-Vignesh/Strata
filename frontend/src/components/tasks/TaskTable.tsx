import type { Task, User } from "../../types/product";
import { PriorityBadge } from "./PriorityBadge";
import { StatusBadge } from "./StatusBadge";
import { formatTaskId } from "./taskPresentation";
import { DueDate } from "./DueDate";

export function TaskTable({ tasks, memberUsers, onEdit, onDelete, onOpen }: { tasks: Task[]; memberUsers: Record<number, User>; onEdit: (task: Task) => void; onDelete: (task: Task) => void; onOpen: (task: Task) => void }) {
  return (
    <div className="task-table-wrap">
      <table className="task-table">
        <thead>
          <tr>
            <th className="px-4 py-3 font-semibold" scope="col">ID</th>
            <th className="min-w-80 px-4 py-3 font-semibold" scope="col">Task</th>
            <th className="px-4 py-3 font-semibold" scope="col">Status</th>
            <th className="px-4 py-3 font-semibold" scope="col">Priority</th>
            <th className="px-4 py-3 font-semibold" scope="col">Due</th>
            <th className="px-4 py-3 font-semibold" scope="col">Assignee</th>
            <th className="px-4 py-3 font-semibold" scope="col">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--strata-border)]">
          {tasks.map((task) => (
            <tr key={task.id}>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-[var(--strata-subtle)]">{formatTaskId(task.id)}</td>
              <td className="px-4 py-3 font-medium text-[var(--strata-text)]"><button className="text-left hover:underline" onClick={() => onOpen(task)} type="button">{task.title}</button></td>
              <td className="whitespace-nowrap px-4 py-3"><StatusBadge status={task.status} /></td>
              <td className="whitespace-nowrap px-4 py-3"><PriorityBadge priority={task.priority} /></td>
              <td className="whitespace-nowrap px-4 py-3"><DueDate dueDate={task.due_date ?? null} status={task.status} /></td>
              <td className="whitespace-nowrap px-4 py-3 text-[var(--strata-muted)]">{task.assignee_user_id === null ? "Unassigned" : (memberUsers[task.assignee_user_id]?.name ?? "Unknown member")}</td>
              <td className="whitespace-nowrap px-4 py-3"><button className="text-button" onClick={() => onEdit(task)} type="button">Edit</button><button className="text-button danger-text" onClick={() => onDelete(task)} type="button">Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
