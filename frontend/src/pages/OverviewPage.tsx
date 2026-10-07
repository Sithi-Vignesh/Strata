import { useProduct } from "../app/ProductContext";
import { DataState } from "../components/data/DataState";
import { PageHeader } from "../components/layout/PageHeader";
import { StatusBadge } from "../components/tasks/StatusBadge";
import { TASK_STATUSES } from "../types/product";

export function OverviewPage() {
  const { tasks, selectedWorkspaceId, selectedProjectId, status, retry } = useProduct();
  const summary = Object.fromEntries(TASK_STATUSES.map((taskStatus) => [taskStatus, tasks.filter((task) => task.status === taskStatus).length])) as Record<(typeof TASK_STATUSES)[number], number>;
  const loading = status === "loading";
  const error = status === "error";
  return <section className="max-w-6xl">
    <PageHeader description="Workspace activity and project progress at a glance." title="Overview" />
    <DataState error={error} errorMessage="Could not load your Strata workspace." loading={loading} loadingMessage="Loading workspace summary…" onRetry={retry} />
    {!loading && !error && selectedWorkspaceId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No workspaces available.</p>}
    {!loading && !error && selectedWorkspaceId !== null && selectedProjectId === null && <p className="py-10 text-sm text-[var(--strata-muted)]">No projects in this workspace.</p>}
    {!loading && !error && selectedProjectId !== null && tasks.length > 0 && <div className="mt-6 space-y-8"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><SummaryMetric label="Total tasks" value={tasks.length} /><SummaryMetric label="To do" value={summary.TODO} /><SummaryMetric label="In progress" value={summary.IN_PROGRESS} /><SummaryMetric label="Done" value={summary.DONE} /></div><section aria-labelledby="work-by-status-heading"><h2 className="text-sm font-semibold text-[var(--strata-text)]" id="work-by-status-heading">Work by status</h2><div className="mt-3 divide-y divide-[var(--strata-border)] rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)]">{TASK_STATUSES.map((taskStatus) => <div className="flex items-center justify-between gap-4 px-4 py-3" key={taskStatus}><StatusBadge status={taskStatus} /><span className="text-sm font-semibold tabular-nums text-[var(--strata-text)]">{summary[taskStatus]}</span></div>)}</div></section></div>}
    {!loading && !error && selectedProjectId !== null && tasks.length === 0 && <p className="py-10 text-sm text-[var(--strata-muted)]">No tasks in this project.</p>}
  </section>;
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return <article className="rounded-md border border-[var(--strata-border)] bg-[var(--strata-surface)] px-4 py-4"><p className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--strata-subtle)]">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums text-[var(--strata-text)]">{value}</p></article>;
}
