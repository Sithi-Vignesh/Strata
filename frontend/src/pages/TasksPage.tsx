import { useEffect, useState } from "react";
import { getTasks } from "../api/tasks";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { TaskTable } from "../components/tasks/TaskTable";
import type { Task } from "../types/task";

export function TasksPage() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    void getTasks().then(
      (value) => {
        if (active) {
          setTasks(value);
          setLoading(false);
        }
      },
      () => {
        if (active) {
          setTasks(null);
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

  return (
    <section className="max-w-6xl">
      <PageHeader description="Track and review work across the Strata workspace." title="Tasks" />
      <DataState error={error} loading={loading} loadingMessage="Loading tasks…" onRetry={retry} />
      {!loading && !error && tasks && (tasks.length ? <TaskTable tasks={tasks} /> : <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks found.</p>)}
    </section>
  );
}
