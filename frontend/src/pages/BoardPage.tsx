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
  const [dragging, setDragging] = useState<Task | null>(null);
  const [dropStatus, setDropStatus] = useState<TaskStatus | null>(null);
  const loading = status === "loading";
  const error = status === "error";
  useEffect(() => { if (detail !== null) { const current = tasks.find((task) => task.id === detail.id); if (!current || current.project_id !== selectedProjectId) setDetail(null); else if (current !== detail) setDetail(current); } }, [detail, selectedProjectId, tasks]);
  const board = Object.fromEntries(TASK_STATUSES.map((taskStatus) => [taskStatus, tasks.filter((task) => task.status === taskStatus)])) as Record<TaskStatus, Task[]>;
  const moveTask = async (task: Task, nextStatus: TaskStatus) => { if (task.status === nextStatus || pendingTaskId !== null) return; setPendingTaskId(task.id); setMutationError(null); setNotice(null); try { await updateTask(task.id, { status: nextStatus }); window.dispatchEvent(new Event("strata:notifications-changed")); try { await refreshTasks(); } catch { setNotice("Task status was saved, but the latest task list could not be refreshed."); } } catch (reason) { setMutationError(reason instanceof Error ? reason.message : "Could not update task status."); } finally { setPendingTaskId(null); } };
  return <section className="page-container board-page"><PageHeader eyebrow="Visual workflow" description="Move work through each stage with clear, accessible status controls." title="Board" /><DataState error={error} errorMessage="Could not load tasks for this project." loading={loading} loadingMessage="Loading board…" onRetry={retry} />
    {mutationError && <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900" role="alert">{mutationError}</p>}{notice && <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="status">{notice}</p>}
    {!loading && !error && selectedProjectId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p>}{!loading && !error && selectedProjectId !== null && tasks.length === 0 && <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks in this project.</p>}
    {!loading && !error && selectedProjectId !== null && tasks.length > 0 && <div className="board-scroll"><div className="kanban-board">{TASK_STATUSES.map((taskStatus) => <BoardColumn dragging={dragging} dropActive={dropStatus === taskStatus} key={taskStatus} memberUsers={memberUsers} onDragEnd={() => { setDragging(null); setDropStatus(null); }} onDragStart={setDragging} onDrop={(status) => { const task = dragging; setDragging(null); setDropStatus(null); if (task) void moveTask(task, status); }} onOpen={setDetail} onStatusChange={moveTask} onTarget={setDropStatus} pendingTaskId={pendingTaskId} status={taskStatus} tasks={board[taskStatus]} />)}</div></div>}{detail && <TaskDetailModal currentUser={currentUser} memberUsers={memberUsers} onClose={() => setDetail(null)} task={detail} />}</section>;
}

function BoardColumn({ status, tasks, memberUsers, pendingTaskId, dragging, dropActive, onStatusChange, onOpen, onDragStart, onDragEnd, onTarget, onDrop }: { status: TaskStatus; tasks: Task[]; memberUsers: Record<number, User>; pendingTaskId: number | null; dragging: Task | null; dropActive: boolean; onStatusChange: (task: Task, status: TaskStatus) => void; onOpen: (task: Task) => void; onDragStart: (task: Task) => void; onDragEnd: () => void; onTarget: (status: TaskStatus | null) => void; onDrop: (status: TaskStatus) => void }) {
  const available = dragging !== null && dragging.status !== status;
  return <section aria-labelledby={`${status}-heading`} className={`kanban-column kanban-${status.toLowerCase()} ${dropActive && available ? "kanban-drop-active" : ""}`} onDragEnter={(event) => { if (available) { event.preventDefault(); onTarget(status); } }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onTarget(null); }} onDragOver={(event) => { if (available) { event.preventDefault(); event.dataTransfer.dropEffect = "move"; } }} onDrop={(event) => { event.preventDefault(); if (available) onDrop(status); }}><div className="kanban-heading"><div><i /><h2 id={`${status}-heading`}>{formatTaskStatus(status)}</h2></div><span>{tasks.length}</span></div>{available && <p className="kanban-drop-label">Drop to move to {formatTaskStatus(status)}</p>}<div className="kanban-cards">{tasks.length === 0 && <p className="kanban-empty">No tasks in this stage</p>}{tasks.map((task) => <TaskCard key={task.id} memberUsers={memberUsers} onDragEnd={onDragEnd} onDragStart={onDragStart} onOpen={onOpen} onStatusChange={onStatusChange} statusPending={pendingTaskId === task.id} task={task} />)}</div></section>;
}
