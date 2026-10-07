import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { TaskCard } from "../components/tasks/TaskCard";
import { formatTaskStatus } from "../components/tasks/taskPresentation";
import type { Task, TaskStatus, User } from "../types/product";
import { TASK_STATUSES } from "../types/product";

export function BoardPage() {
  const { tasks, memberUsers, selectedProjectId, status, retry } = useProduct();
  const loading = status === "loading";
  const error = status === "error";
  const board = Object.fromEntries(TASK_STATUSES.map((taskStatus) => [taskStatus, tasks.filter((task) => task.status === taskStatus)])) as Record<TaskStatus, Task[]>;
  return <section className="max-w-none"><PageHeader description="Follow task progress across each stage of work." title="Board" /><DataState error={error} errorMessage="Could not load tasks for this project." loading={loading} loadingMessage="Loading board…" onRetry={retry} />
    {!loading && !error && selectedProjectId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p>}
    {!loading && !error && selectedProjectId !== null && tasks.length === 0 && <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks in this project.</p>}
    {!loading && !error && selectedProjectId !== null && tasks.length > 0 && <div className="mt-6 overflow-x-auto pb-2"><div className="grid min-w-[48rem] grid-cols-3 gap-4">{TASK_STATUSES.map((taskStatus) => <BoardColumn key={taskStatus} memberUsers={memberUsers} status={taskStatus} tasks={board[taskStatus]} />)}</div></div>}</section>;
}

function BoardColumn({ status, tasks, memberUsers }: { status: TaskStatus; tasks: Task[]; memberUsers: Record<number, User> }) {
  return <section aria-labelledby={`${status}-heading`} className="rounded-md border border-[var(--strata-border)] bg-slate-50 p-3"><div className="flex items-center justify-between gap-3"><h2 className="text-sm font-semibold text-[var(--strata-text)]" id={`${status}-heading`}>{formatTaskStatus(status)}</h2><span className="text-xs font-semibold tabular-nums text-[var(--strata-subtle)]">{tasks.length}</span></div><div className="mt-3 space-y-3">{tasks.map((task) => <TaskCard key={task.id} memberUsers={memberUsers} task={task} />)}</div></section>;
}
