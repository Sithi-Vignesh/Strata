import { useEffect, useState } from "react";
import { getBoardTasks } from "../api/tasks";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { TaskCard } from "../components/tasks/TaskCard";
import { formatTaskStatus } from "../components/tasks/taskPresentation";
import { TASK_STATUSES, type Task, type TaskStatus } from "../types/task";

export function BoardPage() {
  const [board, setBoard] = useState<Record<TaskStatus, Task[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    void getBoardTasks().then(
      (value) => {
        if (active) {
          setBoard(value);
          setLoading(false);
        }
      },
      () => {
        if (active) {
          setBoard(null);
          setError(true);
          setLoading(false);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);

  const retry = () => setAttempt((value) => value + 1);
  const taskCount = board ? Object.values(board).reduce((count, tasks) => count + tasks.length, 0) : 0;

  return (
    <section className="max-w-none">
      <PageHeader description="Follow task progress across each stage of work." title="Board" />
      <DataState error={error} loading={loading} loadingMessage="Loading board…" onRetry={retry} />
      {!loading && !error && board && taskCount > 0 && (
        <div className="mt-6 overflow-x-auto pb-2">
          <div className="grid min-w-[70rem] grid-cols-5 gap-4">
            {TASK_STATUSES.map((status) => <BoardColumn key={status} status={status} tasks={board[status]} />)}
          </div>
        </div>
      )}
      {!loading && !error && (!board || taskCount === 0) && <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks are available for this board.</p>}
    </section>
  );
}

function BoardColumn({ status, tasks }: { status: TaskStatus; tasks: Task[] }) {
  return (
    <section aria-labelledby={`${status}-heading`} className="rounded-md border border-[var(--strata-border)] bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--strata-text)]" id={`${status}-heading`}>{formatTaskStatus(status)}</h2>
        <span className="text-xs font-semibold tabular-nums text-[var(--strata-subtle)]">{tasks.length}</span>
      </div>
      <div className="mt-3 space-y-3">
        {tasks.map((task) => <TaskCard key={task.id} task={task} />)}
      </div>
    </section>
  );
}
