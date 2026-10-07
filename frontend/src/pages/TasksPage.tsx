import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { TaskTable } from "../components/tasks/TaskTable";

export function TasksPage() {
  const { tasks, memberUsers, selectedWorkspaceId, selectedProjectId, status, retry } = useProduct();
  const loading = status === "loading";
  const error = status === "error";
  return <section className="max-w-6xl"><PageHeader description="Track and review work across the Strata workspace." title="Tasks" /><DataState error={error} errorMessage="Could not load tasks for this project." loading={loading} loadingMessage="Loading tasks…" onRetry={retry} />
    {!loading && !error && selectedWorkspaceId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No workspaces available.</p>}
    {!loading && !error && selectedWorkspaceId !== null && selectedProjectId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p>}
    {!loading && !error && selectedProjectId !== null && (tasks.length ? <TaskTable memberUsers={memberUsers} tasks={tasks} /> : <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks in this project.</p>)}</section>;
}
