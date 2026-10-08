import { useEffect, useState } from "react";
import { updateTask } from "../api/product";
import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { TaskCard } from "../components/tasks/TaskCard";
import { TaskDetailModal } from "../components/tasks/TaskDetailModal";
import { formatTaskStatus } from "../components/tasks/taskPresentation";
import { TASK_STATUSES, type Task, type TaskStatus, type User } from "../types/product";

export function BoardPage() {
  const { tasks, currentUser, memberUsers, selectedProjectId, status, retry, refreshTasks } = useProduct();
  const [pendingTaskId, setPendingTaskId] = useState<number | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detail, setDetail] = useState<Task | null>(null);
  const loading = status === "loading";
  const error = status === "error";
  useEffect(() => { if (detail !== null && detail.project_id !== selectedProjectId) setDetail(null); }, [detail, selectedProjectId]);
  const board = Object.fromEntries(TASK_STATUSES.map((taskStatus) => [taskStatus, tasks.filter((task) => task.status === taskStatus)])) as Record<TaskStatus, Task[]>;
  const moveTask = async (task: Task, nextStatus: TaskStatus) => { if (task.status === nextStatus || pendingTaskId !== null) return; setPendingTaskId(task.id); setMutationError(null); setNotice(null); try { await updateTask(task.id, { status: nextStatus }); try { await refreshTasks(); } catch { setNotice("Task status was saved, but the latest task list could not be refreshed."); } } catch (reason) { setMutationError(reason instanceof Error ? reason.message : "Could not update task status."); } finally { setPendingTaskId(null); } };
  return <section className="max-w-none"><PageHeader description="Follow task progress across each stage of work." title="Board" /><DataState error={error} errorMessage="Could not load tasks for this project." loading={loading} loadingMessage="Loading board…" onRetry={retry} />
    {mutationError && <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900" role="alert">{mutationError}</p>}{notice && <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="status">{notice}</p>}
    {!loading && !error && selectedProjectId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p>}{!loading && !error && selectedProjectId !== null && tasks.length === 0 && <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks in this project.</p>}
    {!loading && !error && selectedProjectId !== null && tasks.length > 0 && <div className="mt-6 overflow-x-auto pb-2"><div className="grid min-w-[48rem] grid-cols-3 gap-4">{TASK_STATUSES.map((taskStatus) => <BoardColumn key={taskStatus} memberUsers={memberUsers} onOpen={setDetail} onStatusChange={moveTask} pendingTaskId={pendingTaskId} status={taskStatus} tasks={board[taskStatus]} />)}</div></div>}{detail && <TaskDetailModal currentUser={currentUser} memberUsers={memberUsers} onClose={() => setDetail(null)} task={detail} />}</section>;
}

function BoardColumn({ status, tasks, memberUsers, pendingTaskId, onStatusChange, onOpen }: { status: TaskStatus; tasks: Task[]; memberUsers: Record<number, User>; pendingTaskId: number | null; onStatusChange: (task: Task, status: TaskStatus) => void; onOpen: (task: Task) => void }) {
  return <section aria-labelledby={`${status}-heading`} className="rounded-md border border-[var(--strata-border)] bg-slate-50 p-3"><div className="flex items-center justify-between gap-3"><h2 className="text-sm font-semibold text-[var(--strata-text)]" id={`${status}-heading`}>{formatTaskStatus(status)}</h2><span className="text-xs font-semibold tabular-nums text-[var(--strata-subtle)]">{tasks.length}</span></div><div className="mt-3 space-y-3">{tasks.map((task) => <TaskCard key={task.id} memberUsers={memberUsers} onOpen={onOpen} onStatusChange={onStatusChange} statusPending={pendingTaskId === task.id} task={task} />)}</div></section>;
}
